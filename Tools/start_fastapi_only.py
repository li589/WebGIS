"""Quick start of FastAPI service only."""
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(r"d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\backend")))

print("[INFO] Starting FastAPI on http://127.0.0.1:8000...")
print("[INFO] Press Ctrl+C to stop")
print("=" * 60)

# Start uvicorn directly
import uvicorn
from app.main import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
