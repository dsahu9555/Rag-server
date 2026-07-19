from celery import Celery
from database import supabase
from typing import cast, Optional,List
from database import s3_client, BUCKET_NAME
import os
from unstructured.partition.pdf import partition_pdf
from unstructured.partition.docx import partition_docx
from unstructured.partition.html import partition_html
from unstructured.partition.pptx import partition_pptx
from unstructured.partition.text import partition_text
from unstructured.partition.md import partition_md

from unstructured.chunking.title import chunk_by_title
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.documents import Document
import json

from scrapingbee import ScrapingBeeClient

from dotenv import load_dotenv
load_dotenv()

scrapingbee_client = ScrapingBeeClient(api_key=os.getenv("SCRAPINGBEE_API_KEY"))


llm = ChatOpenAI(model="gpt-4o", temperature=0)

embedding_model = OpenAIEmbeddings(
    model="text-embedding-3-small",
    dimensions=1536
)

celery_app = Celery(
    "document_processing", # Name of celery app
    broker="redis://localhost:6379",
    backend="redis://localhost:6379"
)


def update_status(document_id: str, status: str, details: dict = None): # type: ignore
    """ Update document processing status with optional details """

    # get current document
    result = supabase.table("project_documents").select("processing_details").eq("id", document_id).execute()

    # start with existing details or empty dict
    current_details = {}

    if result.data and result.data[0]["processing_details"]: # type: ignore
        current_details = result.data[0]["processing_details"] # type: ignore

    # Add new details if provided
    if details:
        current_details.update(details)         # type: ignore

    # update document
    supabase.table("project_documents").update({
        "processing_status": status,
        "processing_details" : current_details
    }).eq("id", document_id).execute()



@celery_app.task
def process_document(document_id: str):
    """ 
        Real Document Processing
    """
    try:
        
        doc_result = supabase.table("project_documents").select("*").eq("id", document_id).execute()
       
        document = doc_result.data[0]
       
        document = cast(dict, document)
        source_type = document.get('source_type', 'file')
        # step 1. Download and Partition
       
        update_status(document_id, "partitioning")

        elements = download_and_partition(document_id, document)
        tables = sum(1 for e in elements if e.category == "Table")  # type: ignore
        images = sum(1 for e in elements if e.category == "Image")  # type: ignore
        text_elements = sum(1 for e in elements if e.category in ["NarrativeText", "Title", "Text"]) # type: ignore
        print(f"Extracted: {tables} table, {images} image, {text_elements} text elements ")

        # step 2. chunk elements
        chunks, chunking_metrics = chunk_elements(elements)
        
        update_status(document_id, "summarising", {
            "chunking": chunking_metrics
        })
        # step 3. summarizing chunks
        processed_chunks = summarize_chunks(chunks, document_id, source_type)


        # step 4. vectorization & storing
        update_status(document_id, "vectorization")

        stored_chunk_ids = store_chunks_with_embeddings(document_id, processed_chunks)

        #  Mark as completed
        update_status(document_id, "completed")
        print(f"Real Celery task completed for document: {document_id} with {len(stored_chunk_ids)} chunks")

        return {
            "status": "success",
            "document_id": document_id
        }
    

    except Exception as e:
        print(f"==================== In process document exception ================================= \n {str(e)}")


def download_and_partition(document_id: str, document: dict):
    """ Download document from S3 / Crawl url and partition into elements """
    print(f"Downloading and partitioning the document {document_id}")

    source_type = document.get("source_type", "file")

    if source_type == "url":
        
        url = document["source_url"]

        response = scrapingbee_client.get(url)

        #  save to temp file
        temp_file = f"/tmp/{document_id}.html"
        with open(temp_file, "wb") as f:
            f.write(response.content)
        
        elements = partition_document(temp_file, "html", source_type="url")

    else:
        # handle file processing
        
        s3_key = document["s3_key"]
        filename = document["filename"]
        filetype = filename.split(".")[-1].lower()

        #  Download to temp location
        temp_file = f"/tmp/{document_id}.{filetype}"
        s3_client.download_file(BUCKET_NAME,s3_key, temp_file)

        elements = partition_document(temp_file, filetype, source_type=="file")


    element_summary = analyze_elements(elements)
    update_status(document_id, "chunking", {
        "partitioning": {
            "elements_found": element_summary
        }
    })
    os.remove(temp_file)
    return elements


def partition_document(temp_file: str, file_type: str, source_type: str = "file"):
    """ Partition based on file type """

    if source_type == "url":
        return partition_html(
            filename=temp_file
        )

    elif file_type == "pdf":
        return partition_pdf(
            filename=temp_file,
            strategy="hi_res",
            infer_table_structure=True,
            extract_image_block_types=["Image"],
            extract_image_block_to_payload=True
        )
    elif file_type == "pptx":
        return partition_pptx(
            filename=temp_file,
            strategy="hi_res",
            infer_table_structure=True
        )
    elif file_type == "txt":
        return partition_text(
            filename=temp_file,
        )
    elif file_type == "md":
        return partition_md(
            filename=temp_file,
        )
    
    



def analyze_elements(elements):
    """Count different types of element found in document"""
    text_count = 0
    image_count = 0
    table_count = 0
    title_count = 0
    other_count = 0

    for element in elements:
        element_name = type(element).__name__

        if element_name == "Table":
            table_count+=1
        elif element_name == "Image":
            image_count+=1
        elif element_name in ["Title","Header"]:
            title_count+=1
        elif element_name in ["NarrativeText", "Text", "ListItem", "FigureCaption"]:
            text_count+=1
        else:
            other_count+=1

        # Return a simple dictionary
    return {
        "text": text_count,
        "images": image_count,
        "tables": table_count,
        "titles": title_count,
        "other": other_count
    }


def chunk_elements(elements):
    """
    Create intelligent chunks by using title-based strategy."""
    print(f"Create smart chunks....")

    chunks  = chunk_by_title(
        elements=elements,
        max_characters=3000,
        new_after_n_chars=2400,
        combine_text_under_n_chars=500
    )

    print(f"Created {len(chunks)} chunks")
    total_chunks = len(chunks)
    # collect chunking metrics
    
    chunking_metrics = {
        "total_chunks": total_chunks
    }
    return chunks, chunking_metrics

def summarize_chunks(chunks, document_id, source_type):
    """Process all the chunks with AI summaries"""
    print(f"Processing all the chunks with AI summaries")
    processed_chunks = []
    total_chunks = len(chunks)

    for i, chunk in enumerate(chunks):
        current_chunk = i+1
        print(f" Processing chunk {current_chunk}/{total_chunks}")

        # update progress directly
        update_status(document_id, "summarising", {
            "summarising" : {
                "current_chunk": current_chunk,
                "total_chunk": total_chunks
            }
        })


        # extract content from the chunk
        content_data = separate_content_types(chunk, source_type)

        print(f"    Types found: {content_data["types"]}")
        print(f"    Tables: {len(content_data["tables"])}")
        print(f"    Images: {len(content_data["images"])}")

        # create ai summay if chunks contain images/tables
        if content_data["tables"] or content_data["images"]:
            print(f"    - Creating AI Summary for the mixed content...")
            enhanced_content = create_ai_enhanced_summary(
                content_data["text"],
                content_data["tables"],
                content_data["images"]
            )
        else:
            enhanced_content = content_data["text"]


        
         # Build the original_content structure
        original_content = {'text': content_data['text']}
        if content_data['tables']:
            original_content['tables'] = content_data['tables']
        if content_data['images']:
            original_content['images'] = content_data['images']
        
        # Create processed chunk with all data
        processed_chunk = {
            'content': enhanced_content,
            'original_content': original_content, 
            'type': content_data['types'],
            'page_number': get_page_number(chunk, i),
            'char_count': len(enhanced_content)
        }

        processed_chunks.append(processed_chunk)
    
    print(f"✅ Processed {len(processed_chunks)} chunks")
    return processed_chunks


def get_page_number(chunk, chunk_index):
    """Get page number from chunk or use fallback"""
    if hasattr(chunk, 'metadata'):
        page_number = getattr(chunk.metadata, 'page_number', None)
        if page_number is not None:
            return page_number
    
    # Fallback: use chunk index as page number
    return chunk_index + 1

def separate_content_types(chunk, source_type = "file"):
    """Analyze what types of content are in a chunk"""

    is_url_source = source_type == "url"

    content_data = {
        "text": chunk.text,
        "tables": [],
        "images": [],
        "types": ["text"]
        }
    
    #check for tables and images in original elements
    if hasattr(chunk, "metadata") and hasattr(chunk.metadata, "orig_elements"):
        for element in chunk.metadata.orig_elements:
            element_type = type(element).__name__

            # handle tables
            if element_type == "Table":
                content_data["types"].append("table")
                table_html = getattr(element.metadata, "text_as_html", element.text)
                content_data["tables"].append(table_html)

            # handle images
            elif element_type == "Image" and not is_url_source:
                if hasattr(chunk, "metadata") and hasattr(chunk.metadata, "Image") and element.metadata.image_base64 is not None:
                    content_data["types"].append("image")
                    content_data["images"].append(element.metadata.iimage_base64)
    
    content_data["types"] = list(set(content_data["types"]))
    return content_data

def create_ai_enhanced_summary(text, tables, images):
    """Create Ai-enhanced summary for mixed content"""

    try:
        

        prompt_text = f"""Create a searchable index for this document content.
        CONTENT To ANALYZE:
        TEXT CONTENT:
        {text}
        
         """
        # add table if present
        if tables:
            prompt_text+="Tables:\n"
            for i, table in enumerate(tables):
                prompt_text+= f"Table {i+1}:\n{table}\n\n"

            prompt_text += """
Generate a structured search index (aim for 250-400 words):

QUESTIONS: List 5-7 key questions this content answers (use what/how/why/when/who variations)

KEYWORDS: Include:
- Specific data (numbers, dates, percentages, amounts)
- Core concepts and themes
- Technical terms and casual alternatives
- Industry terminology

VISUALS (if images present):
- Chart/graph types and what they show
- Trends and patterns visible
- Key insights from visualizations

DATA RELATIONSHIPS (if tables present):
- Column headers and their meaning
- Key metrics and relationships
- Notable values or patterns

Focus on terms users would actually search for. Be specific and comprehensive.

SEARCH INDEX:"""
        # BUILD MESSAGE CONTENT STARTING WITH TEXT
        message_content = [{"type": "text", "text": prompt_text}]

        #Add images to the message
        for i, image_base64 in enumerate(images):
            message_content.append({                      # type: ignore
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
            })

        #send to ai and get response
        message = HumanMessage(content=message_content)   # type: ignore
        response = llm.invoke([message])

        return response.content
    
    except Exception as e:
        print(f"     AI summary failed: {e}")
        # Fallback to simple summary
        summary = f"{text[:300]}..."
        if tables:
            summary += f" [Contains {len(tables)} table(s)]"
        if images:
            summary += f" [Contains {len(images)} image(s)]"
        return summary

def store_chunks_with_embeddings(document_id: str, processed_chunks: list):
    """ Generate embeddings and store chunk in one efficient operation"""
    print("Generating embeddings and storing chunks...")

    if not processed_chunks:
        print("No chunk to process")
        return []
    
    # step 1. Generate embeddings for all chunks
    print(f"Generating embeddings for {len(processed_chunks)} chunks")

    # Extract content for embedding generation
    texts = [chunk_data["content"] for chunk_data in processed_chunks]

    # Generate embedding in batches to avoid api limits
    batch_size = 10
    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i:i+ batch_size]
        batch_embeddings = embedding_model.embed_documents(batch_texts)
        all_embeddings.extend(batch_embeddings)
        print(f"✅ Generated embeddings for batch {i // batch_size + 1}/{(len(texts) + batch_size - 1) // batch_size}")

    stored_chunk_ids = []

    #  step 2: Store chunks with embeddings
    print("Storing chunks with embeddings in database...")
    for i, (chunk_data, embedding) in enumerate(zip(processed_chunks, all_embeddings)):
        chunk_data_with_embedding = {
            **chunk_data,
            "document_id": document_id,
            "chunk_index": i,
            "embedding" : embedding
        }

        result = supabase.table("document_chunks").insert(chunk_data_with_embedding).execute()
        stored_chunk_ids.append(result.data[0]["id"])

    print(f"Successfully stored {len(processed_chunks)} chunks with embedddings")
    return stored_chunk_ids

