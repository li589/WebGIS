from pathlib import Path
from ingest.station import parse_ismn_stm_file, _split_tokens

# Create test file
p = Path("d:/Workspace/mat2py/test_debug.stm")
content = "2020/01/01 06 0.25 G 30.0 115.0 100.0 5.0 5.0\n2020/01/02 06 0.25 G\n"
p.write_text(content, encoding="utf-8")
print("Content:", repr(content))
lines = content.splitlines()
print("Lines:", lines)
first_tokens = _split_tokens(lines[0])
print("First tokens:", first_tokens)
print("Token count:", len(first_tokens))

recs = parse_ismn_stm_file(p)
print("Parsed records:", len(recs))
for r in recs:
    print(f"  {r.year}-{r.month:02d}-{r.day:02d} h={r.hour}: sm={r.soil_moisture}, depth={r.depth_lower}, lat={r.lat}, flag={r.quality_flag}")

p.unlink()
