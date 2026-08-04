import sys
from pathlib import Path

# Check Python path
sys.path.insert(0, str(Path(r"d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\backend")))

try:
    from app.core.config import BACKEND_ROOT, _RUNTIME_ROOT
    print(f"[OK] Backend config loaded")
    print(f"BACKEND_ROOT: {BACKEND_ROOT}")
    print(f"_RUNTIME_ROOT: {_RUNTIME_ROOT}")
    
    # Check if .env exists
    env_path = Path(__file__).parents[1].parent.parent / ".env"
    if env_path.exists():
        print(f".env file exists: {env_path}")
    else:
        print(f".env file NOT found: {env_path}")
        
except Exception as e:
    print(f"[ERROR] Failed to load config: {e}")
    import traceback
    traceback.print_exc()
