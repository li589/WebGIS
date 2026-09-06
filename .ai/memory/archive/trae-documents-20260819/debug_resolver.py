"""Debug: check if get_definition works and what build_job_request_payload produces"""
import sys, os, json
backend_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'Code', 'backend')
sys.path.insert(0, os.path.abspath(backend_dir))
os.chdir(os.path.abspath(backend_dir))

# Set env
os.environ['ENVIRONMENT'] = 'development'
os.environ['BACKEND_ENV'] = 'development'

from app.services.workflow_definition_service import get_definition, list_definitions

# First trigger sync
print("=== Triggering sync via list_definitions ===")
defs = list_definitions()
print(f"Total definitions: {len(defs)}")

# Now check specific definitions
for name in ['fy_tb_online_read', 'ndvi_online_read']:
    print(f"\n=== get_definition('{name}') ===")
    result = get_definition(name)
    if result is None:
        print(f"  Result: None")
    else:
        print(f"  Type: {type(result)}")
        if isinstance(result, dict):
            print(f"  Keys: {list(result.keys())}")
            print(f"  workflow_id: {result.get('workflow_id')}")
            print(f"  nodes count: {len(result.get('nodes', []))}")
        else:
            print(f"  Value: {str(result)[:200]}")

# Now test the request builder
print("\n=== Testing PythonProviderRequestBuilder ===")
from app.services.python_provider_request_builder import PythonProviderRequestBuilder
from shared.contracts.api_contracts import WorkflowSubmitRequest, WorkflowCommandType, AlgorithmWorkflowRequest

algo_req = AlgorithmWorkflowRequest(workflow_name='fy_tb_online_read')
payload = WorkflowSubmitRequest(
    command_type=WorkflowCommandType.analysis,
    layer_id='ref-fy-tb-202512-mwri',
    algorithm_request=algo_req,
)

builder = PythonProviderRequestBuilder()
result = builder.build_job_request_payload(run_id='test-debug-001', payload=payload)
print(f"  workflow_name: {result.get('workflow_name')}")
print(f"  workflow_definition present: {'workflow_definition' in result}")
if 'workflow_definition' in result:
    wf_def = result['workflow_definition']
    print(f"  workflow_definition type: {type(wf_def)}")
    if isinstance(wf_def, dict):
        print(f"  workflow_definition keys: {list(wf_def.keys())}")
        print(f"  workflow_definition.workflow_id: {wf_def.get('workflow_id')}")
