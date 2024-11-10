from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, Response
import sqlite3
import uuid
import uvicorn
from contextlib import contextmanager
import socket
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.cors import CORSMiddleware

app = FastAPI()

# Add Gzip compression
app.add_middleware(GZipMiddleware, minimum_size=500)

# CORS with optimized settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files with caching
app.mount("/static", StaticFiles(directory="static", check_dir=False), name="static")
templates = Jinja2Templates(directory="templates")

# Use connection pooling for SQLite
DB_POOL = {}

def get_db_connection():
    """Get a connection from the pool or create a new one"""
    pid = id(socket.socket())  # Unique identifier for the current process
    if pid not in DB_POOL:
        conn = sqlite3.connect('pastes.db', check_same_thread=False)
        conn.execute('PRAGMA journal_mode=WAL')  # Use Write-Ahead Logging
        conn.execute('PRAGMA synchronous=NORMAL')  # Faster disk writes
        conn.execute('PRAGMA cache_size=-64000')  # 64MB cache
        conn.row_factory = sqlite3.Row
        DB_POOL[pid] = conn
    return DB_POOL[pid]

@contextmanager
def get_db():
    conn = get_db_connection()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()

def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS pastes (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Add index for faster lookups
        conn.execute('CREATE INDEX IF NOT EXISTS idx_paste_id ON pastes(id)')

# Initialize database on startup
init_db()

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        "index.html", 
        {"request": request},
        headers={"Cache-Control": "public, max-age=3600"}
    )

@app.post("/publish")
async def publish(request: Request, content: str = Form(...)):
    paste_id = str(uuid.uuid4())[:5]
    
    with get_db() as conn:
        conn.execute(
            "INSERT INTO pastes (id, content) VALUES (?, ?)",
            (paste_id, content)
        )
    
    # Get the base URL from the request
    base_url = str(request.base_url).rstrip('/')
    return f"{base_url}/{paste_id}"

@app.get("/{paste_id}")
async def get_paste(request: Request, paste_id: str):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT content FROM pastes WHERE id = ?", 
            (paste_id,)
        )
        result = cursor.fetchone()
        
        if result:
            return templates.TemplateResponse(
                "paste.html", 
                {
                    "request": request, 
                    "content": result[0], 
                    "paste_id": paste_id
                },
                headers={"Cache-Control": "public, max-age=31536000"}
            )
        return RedirectResponse(url="/")

@app.get("/raw/{paste_id}")
async def get_raw_paste(paste_id: str):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT content FROM pastes WHERE id = ?", (paste_id,))
        result = cursor.fetchone()
        
        if result:
            # Return plain text response
            return Response(
                content=result[0],
                media_type="text/plain",
                headers={"Cache-Control": "public, max-age=31536000"}
            )
        return RedirectResponse(url="/")

if __name__ == "__main__":
    try:
        uvicorn.run(
            "main:app", 
            host="127.0.0.1", 
            port=3000,
            workers=4,  # Multiple workers for better performance
            loop="uvloop",  # Faster event loop
            http="httptools",  # Faster HTTP parsing
            reload=True
        )
    except Exception as e:
        print(f"Failed to start server: {e}")