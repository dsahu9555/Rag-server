from supabase import Client, create_client
from dotenv import load_dotenv
import os
load_dotenv()

supabase_url = os.getenv("SUPABASE_API_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_KEY")

if not supabase_url or not supabase_key:
    raise ValueError("Missing supabase credentials")

supabase : Client = create_client(supabase_url, supabase_key)

