"""Install dependencies using pip directly."""
import subprocess
import sys

result = subprocess.run([sys.executable, "-m", "ensurepip"], capture_output=True)
if result.returncode != 0:
    print("Ensure pip failed:", result.stderr.decode())
    sys.exit(1)

print("[INFO] Attempting to install python-dotenv...")
result = subprocess.run([sys.executable, "-m", "pip", "install", "python-dotenv==1.0.0"], capture_output=True, text=True)

if result.returncode == 0:
    print("[OK] python-dotenv installed successfully")
else:
    print("[ERROR] Failed to install python-dotenv:")
    print(result.stderr)
    sys.exit(1)
