"""端到端测试：提交 workflow-run 并验证 Celery 异步消费。"""
import requests
import time
import json

BASE_URL = "http://127.0.0.1:8000"

def test_workflow_submission():
    """测试工作流提交和状态轮询。"""
    print("=" * 60)
    print("端到端测试：Celery 真实消费链验证")
    print("=" * 60)
    
    # 1. 提交 workflow-run
    print("\n[1] 提交 workflow-run 请求...")
    payload = {
        "command_type": "analysis",
        "command_label": "E2E 测试任务",
        "priority": "normal",
        "resource_profile": "standard",
        "parameters": {
            "test_mode": True,
            "description": "Celery 消费链端到端验证"
        }
    }
    
    try:
        response = requests.post(f"{BASE_URL}/workflow-runs", json=payload, timeout=5)
        print(f"响应状态码: {response.status_code}")
        
        if response.status_code != 202:
            print(f"❌ 提交失败: {response.text}")
            return False
        
        accepted = response.json()
        run_id = accepted["run_id"]
        status_url = accepted["status_url"]
        
        print(f"✅ 工作流已接受")
        print(f"   run_id: {run_id}")
        print(f"   status: {accepted['status']}")
        print(f"   status_url: {status_url}")
        
    except Exception as e:
        print(f"❌ 提交异常: {e}")
        return False
    
    # 2. 轮询状态（最多等待 30 秒）
    print("\n[2] 轮询任务状态...")
    max_wait = 30
    poll_interval = 2
    elapsed = 0
    
    while elapsed < max_wait:
        time.sleep(poll_interval)
        elapsed += poll_interval
        
        try:
            status_response = requests.get(f"{BASE_URL}{status_url}", timeout=5)
            if status_response.status_code != 200:
                print(f"   查询失败: {status_response.status_code}")
                continue
            
            status_data = status_response.json()
            current_status = status_data["status"]
            
            print(f"   [{elapsed}s] 状态: {current_status}")
            
            # 终态判断
            if current_status in ["succeeded", "failed", "cancelled"]:
                print(f"\n[3] 任务完成")
                print(f"   最终状态: {current_status}")
                print(f"   创建时间: {status_data.get('created_at')}")
                print(f"   更新时间: {status_data.get('updated_at')}")
                
                if current_status == "succeeded":
                    print("✅ 端到端验证成功：任务已提交 → Celery 消费 → 状态回写")
                    return True
                else:
                    print(f"⚠️ 任务失败或取消: {status_data.get('error_message', 'N/A')}")
                    return False
            
        except Exception as e:
            print(f"   查询异常: {e}")
    
    print(f"\n⚠️ 超时：{max_wait}秒内未完成")
    return False

def test_runtime_status():
    """测试运行时状态接口。"""
    print("\n" + "=" * 60)
    print("测试运行时状态接口")
    print("=" * 60)
    
    try:
        response = requests.get(f"{BASE_URL}/runtime/status", timeout=5)
        print(f"响应状态码: {response.status_code}")
        
        if response.status_code == 200:
            status_data = response.json()
            print(f"✅ 运行时状态:")
            print(f"   service_name: {status_data.get('service_name')}")
            print(f"   task_executor: {status_data.get('task_executor')}")
            print(f"   active_runs: {status_data.get('active_runs')}")
            
            celery_info = status_data.get("celery", {})
            if celery_info:
                print(f"   Celery 状态:")
                print(f"     available: {celery_info.get('available')}")
                print(f"     worker_count: {celery_info.get('worker_count')}")
                print(f"     workers: {celery_info.get('workers')}")
            
            return True
        else:
            print(f"❌ 查询失败: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ 查询异常: {e}")
        return False

if __name__ == "__main__":
    # 测试运行时状态
    test_runtime_status()
    
    # 测试工作流提交和消费
    success = test_workflow_submission()
    
    print("\n" + "=" * 60)
    if success:
        print("✅ 所有测试通过")
    else:
        print("⚠️ 部分测试未通过或超时")
    print("=" * 60)
