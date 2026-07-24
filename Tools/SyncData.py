import os
import sys
import paramiko
import hashlib
import stat
import threading
import queue
import posixpath
import shlex
import json
import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from tqdm import tqdm

# 全局初始化 tqdm 的线程锁，防止多线程打印错乱
tqdm.set_lock(threading.RLock())
# ================= 默认配置模板 =================
# 如果不指定 json 文件，将默认使用此配置
CONFIG = {
    # "ssh": {
    #     "host": "172.18.206.109",
    #     "port": 80,
    #     "username": "user03",
    #     "password": "wnai168618",
    #     "timeout": 10
    # },
    # "ssh": {
    #     "host": "172.18.206.109",
    #     "port": 80,
    #     "username": "user03",
    #     "password": "wnai168618",
    #     "timeout": 10
    # },
    "ssh": {
        # 目标主机 IP
        "host": "121.46.19.4",
        # SSH 端口
        "port": 6666,
        # 登录用户名
        "username": "sysu_jxqiuxy_1",
        # 【方式一】密码登录（如果使用密钥，可以注释掉此行）
        # "password": "your_password_here",
        # 【方式二】密钥文件登录（推荐，填写私钥的绝对路径，如 id_rsa）
        # Windows 示例: r"C:\Users\YourUser\.ssh\id_rsa"
        # Linux/Mac 示例: "/home/youruser/.ssh/id_rsa"
        "key_filename": r"C:\Users\likr\Downloads\sysu_jxqiuxy_1.id",
        # 连接超时时间
        "timeout": 10,
    },
    # "ssh": {
    #     # 目标主机 IP
    #     "host": "172.16.98.185",
    #     # SSH 端口
    #     "port": 22,
    #     # 登录用户名
    #     "username": "likr6",
    #     # 【方式一】密码登录（如果使用密钥，可以注释掉此行）
    #     # "password": "your_password_here",
    #     # 【方式二】密钥文件登录（推荐，填写私钥的绝对路径，如 id_rsa）
    #     # Windows 示例: r"C:\Users\YourUser\.ssh\id_rsa"
    #     # Linux/Mac 示例: "/home/youruser/.ssh/id_rsa"
    #     "key_filename": r"C:\Users\likr\Downloads\id_rsa",
    #     # 连接超时时间
    #     "timeout": 10
    # },
    # "ssh": {
    #     # 目标主机 IP
    #     "host": "172.16.98.185",
    #     # SSH 端口
    #     "port": 22,
    #     # 登录用户名
    #     "username": "likai601",
    #     # 【方式一】密码登录（如果使用密钥，可以注释掉此行）
    #     # "password": "your_password_here",
    #     # 【方式二】密钥文件登录（推荐，填写私钥的绝对路径，如 id_rsa）
    #     # Windows 示例: r"C:\Users\YourUser\.ssh\id_rsa"
    #     # Linux/Mac 示例: "/home/youruser/.ssh/id_rsa"
    #     "key_filename": r"C:\Users\likr\Downloads\likai_id_rsa (2)",
    #     # 连接超时时间
    #     "timeout": 10
    # },
    # "ssh": {
    #     "host": "222.200.176.12",
    #     "port": 21,
    #     "username": "Teacher",
    #     "password": "Qiujianxiu.123456",
    #     "timeout": 10
    # },
    # 全局默认路径：当 item 没有填 src 或 dest 时的补全参考
    "default_local_base": r"D:\Workspace\GeoPaper\PlusCode\Data\Landslide\Output\tcdf_point_timeseries_local_2000plus\files",
    "default_remote_base": r"/public/home/likr6/LikrPro/Data/Landslide/",
    # 同步项目列表 (支持 Rsync 风格的末尾斜杠规则)
    # "sync_items":[
    #     # 1. 文件夹内文件互相同步 (等同重命名文件夹)
    #     {"src": "Draw", "dest": "Python/DDCA"},
    #     # 2. 文件 -> 文件 (重命名)
    #     {"src": r"D:\Workspace\test.txt", "dest": "/share/home/user03/new_test.txt"},
    #     # 3. 文件 -> 文件夹内部 (注意 dest 末尾的斜杠)
    #     {"src": r"D:\Workspace\log.txt", "dest": "Python/Logs/"},
    #     # 4. 文件夹 -> 文件夹内部 (将整个 Draw_backup 文件夹放进去)
    #     {"src": "Draw_backup", "dest": "Python/Backups/"},
    #     # 5. 省略 dest，将自动使用 default 路径 + src 的 basename
    #     # {"src": "config.yaml"}
    # ],
    "sync_items": [
        {
            "src": r"D:\Workspace\GeoPaper\PlusCode\Data\Landslide\Output\tcdf_point_timeseries_local_2000plus\files",
            "dest": r"/XYFS01/HOME/sysu_jxqiu/sysu_jxqiuxy_1/LiKr/Data/Landslide/",
            # "src": r"/public/home/likr6/Software",
            # "dest": r"E:\ProjectBackup\ServerBackup",
        },
    ],
    "direction": "Client2Server",  # "Client2Server" (上传) 或 "Server2Client" (下载)
    # 冲突策略:
    # "overwrite": 直接覆盖
    # "skip": 存在即跳过
    # "fast": 【推荐】比对 文件大小 + 最后修改时间(mtime)，一致则跳过
    # "hash": 严格比对 文件大小 + MD5
    "conflict_policy": "fast",
    "workers": 8,  # 推荐 4~16
    "retry_rounds": 1,  # 每个 worker 首轮跑完后，对本 worker 失败文件再重试几轮
    "console_error_limit": 20,  # 控制台最多打印多少条详细错误，更多错误只写日志
    "error_log_path": "",  # 留空则自动生成日志文件
    "failed_tasks_path": "",  # 留空则自动生成最终失败文件清单
    "failed_tasks_input_path": "",  # 读取上次失败清单，仅对失败文件再次同步
}


# ===========================================
class ProgressBarManager:
    """进度条槽位管理器：用于给多线程分配固定的进度条打印行，防止屏幕闪烁"""

    def __init__(self, max_workers):
        self.lock = threading.Lock()
        self.slots = [False] * max_workers

    def acquire_slot(self):
        with self.lock:
            for i in range(len(self.slots)):
                if not self.slots[i]:
                    self.slots[i] = True
                    return i + 1  # 0 号槽位留给 Overall 进度条
            return len(self.slots) + 1

    def release_slot(self, slot):
        with self.lock:
            idx = slot - 1
            if 0 <= idx < len(self.slots):
                self.slots[idx] = False


class SSHConnectionPool:
    def __init__(self, config, pool_size):
        self.config = config
        self.pool_size = pool_size
        self.pool = queue.Queue(maxsize=pool_size)
        self.lock = threading.Lock()
        self.active_connections = []

    def get_connection(self):
        try:
            return self.pool.get_nowait()
        except queue.Empty:
            return self._create_connection()

    def return_connection(self, conn):
        self.pool.put(conn)

    def _create_connection(self):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        # 准备连接参数字典
        connect_params = {
            "hostname": self.config["host"],
            "port": self.config.get("port", 22),
            "username": self.config["username"],
            "timeout": self.config.get("timeout", 10),
        }
        # 获取密钥文件路径（如果存在）
        key_file = self.config.get("key_filename")
        # 获取密码（如果存在）
        password = self.config.get("password")
        # 优先检查密钥文件
        if key_file:
            # 展开用户路径 (例如 ~/.ssh/id_rsa) 并检查文件是否存在
            expanded_key_file = os.path.expanduser(key_file)
            if os.path.exists(expanded_key_file):
                connect_params["key_filename"] = expanded_key_file
            else:
                # 如果指定了 key_filename 但文件不存在，打印警告
                # 在多线程环境下，使用 tqdm.write 打印警告比较安全，但这里还没法简单调用 sync_manager 的 tprint
                # 简单起见先用 print，或者如果连接失败 paramiko 会抛出异常
                print(
                    f"Warning: Key file not found at: {expanded_key_file}, trying password if available."
                )
        # 如果密钥文件没设置或没找到，并且提供了密码，则使用密码
        # Paramiko 实际上允许同时提供 key_filename 和 password，它通常会优先尝试密钥。
        # 为了保险起见，我们都放进去，前提是它们在配置中存在且不为 None
        if password is not None:
            connect_params["password"] = password
        try:
            # 使用解包参数的方式进行连接
            ssh.connect(**connect_params)
        except paramiko.AuthenticationException:
            print(
                "\n[-] Authentication failed. Please check your username, password, or private key path."
            )
            raise
        except Exception as e:
            print(f"\n[-] Connection failed: {e}")
            raise
        sftp = ssh.open_sftp()
        conn = (ssh, sftp)
        with self.lock:
            self.active_connections.append(conn)
        return conn

    def close_all(self):
        for ssh, sftp in self.active_connections:
            try:
                sftp.close()
                ssh.close()
            except:
                pass


class ErrorRecorder:
    """流式错误记录器：把失败信息直接写盘，避免把大量错误堆在内存里。"""

    def __init__(self, log_path, console_limit=20):
        self.log_path = log_path
        self.console_limit = max(0, int(console_limit))
        self.printed_errors = 0
        self.suppressed_errors = 0
        self.total_errors = 0
        self.lock = threading.Lock()
        self.file = open(log_path, "w", encoding="utf-8", buffering=1)
        self.file.write(
            "timestamp\tworker\tphase\tattempt\tdirection\tsource\tdestination\terror\n"
        )

    def _normalize_message(self, message, limit=500):
        text = str(message).replace("\r", " ").replace("\n", " ").strip()
        return text[:limit] + ("..." if len(text) > limit else "")

    def record(self, worker_id, task, phase, attempt, error_message):
        src, dest, direction = task
        error_text = self._normalize_message(error_message)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.lock:
            self.total_errors += 1
            self.file.write(
                f"{ts}\t{worker_id}\t{phase}\t{attempt}\t{direction}\t{src}\t{dest}\t{error_text}\n"
            )
            should_print = self.printed_errors < self.console_limit
            if should_print:
                self.printed_errors += 1
            else:
                self.suppressed_errors += 1
        return should_print, error_text

    def close(self):
        try:
            self.file.close()
        except Exception:
            pass


class FailedTaskRecorder:
    """最终失败文件清单写入器：仅记录重试后仍失败的文件，便于后续补传。"""

    def __init__(self, log_path):
        self.log_path = log_path
        self.lock = threading.Lock()
        self.total_failed_tasks = 0
        self.file = open(log_path, "w", encoding="utf-8-sig", newline="")
        self.writer = csv.DictWriter(
            self.file,
            fieldnames=[
                "timestamp",
                "worker",
                "direction",
                "source",
                "destination",
                "final_attempt",
                "last_error",
            ],
        )
        self.writer.writeheader()

    def record(self, worker_id, task, final_attempt, error_message):
        src, dest, direction = task
        row = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "worker": worker_id,
            "direction": direction,
            "source": src,
            "destination": dest,
            "final_attempt": final_attempt,
            "last_error": str(error_message)
            .replace("\r", " ")
            .replace("\n", " ")
            .strip(),
        }
        with self.lock:
            self.writer.writerow(row)
            self.file.flush()
            self.total_failed_tasks += 1

    def close(self):
        try:
            self.file.close()
        except Exception:
            pass


class SyncManager:
    def __init__(self, config):
        self.config = config
        self.pool = None
        self.main_ssh = None
        self.main_sftp = None
        self.pbar_manager = ProgressBarManager(self.config.get("workers", 8))
        self.results_lock = threading.Lock()
        self.error_recorder = None
        self.failed_task_recorder = None
        self.transferred = 0
        self.skipped = 0
        self.failed = 0
        self.retried = 0

    def tprint(self, msg):
        """保证在 tqdm 进度条上方打印而不打乱进度条"""
        tqdm.write(msg)

    def connect_main(self):
        self.tprint(f"[*] Connecting to {self.config['ssh']['host']}...")
        self.pool = SSHConnectionPool(self.config["ssh"], self.config["workers"])
        self.main_ssh, self.main_sftp = self.pool.get_connection()
        self.tprint("[+] Main connection established.")

    def close(self):
        if self.pool:
            self.pool.close_all()

    def build_error_log_path(self):
        configured_path = str(self.config.get("error_log_path", "")).strip()
        if configured_path:
            return os.path.abspath(os.path.expanduser(configured_path))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.abspath(f"sync_errors_{timestamp}.log")

    def build_failed_tasks_path(self):
        configured_path = str(self.config.get("failed_tasks_path", "")).strip()
        if configured_path:
            return os.path.abspath(os.path.expanduser(configured_path))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.abspath(f"sync_failed_tasks_{timestamp}.csv")

    def setup_error_recorder(self):
        log_path = self.build_error_log_path()
        os.makedirs(os.path.dirname(log_path), exist_ok=True) if os.path.dirname(
            log_path
        ) else None
        self.error_recorder = ErrorRecorder(
            log_path=log_path,
            console_limit=self.config.get("console_error_limit", 20),
        )
        return log_path

    def setup_failed_task_recorder(self):
        failed_path = self.build_failed_tasks_path()
        os.makedirs(os.path.dirname(failed_path), exist_ok=True) if os.path.dirname(
            failed_path
        ) else None
        self.failed_task_recorder = FailedTaskRecorder(failed_path)
        return failed_path

    def get_failed_tasks_input_path(self):
        configured_path = str(self.config.get("failed_tasks_input_path", "")).strip()
        if not configured_path:
            return ""
        return os.path.abspath(os.path.expanduser(configured_path))

    def update_result_counts(self, status):
        with self.results_lock:
            if status == "Transferred":
                self.transferred += 1
            elif status == "Skipped":
                self.skipped += 1
            elif status == "Failed":
                self.failed += 1

    def record_retry(self, count=1):
        with self.results_lock:
            self.retried += count

    def split_tasks_for_workers(self, tasks, worker_count):
        buckets = [[] for _ in range(max(1, worker_count))]
        for index, task in enumerate(tasks):
            buckets[index % len(buckets)].append(task)
        return buckets

    def load_failed_tasks_from_csv(self, csv_path):
        if not csv_path or not os.path.exists(csv_path):
            raise FileNotFoundError(f"Failed task list not found: {csv_path}")
        tasks = []
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            required_cols = {"source", "destination", "direction"}
            if not reader.fieldnames or not required_cols.issubset(
                set(reader.fieldnames)
            ):
                raise ValueError(
                    f"Invalid failed task CSV. Required columns: {sorted(required_cols)}"
                )
            for row in reader:
                src = str(row.get("source", "")).strip()
                dest = str(row.get("destination", "")).strip()
                direction = str(row.get("direction", "")).strip()
                if (
                    not src
                    or not dest
                    or direction not in {"Client2Server", "Server2Client"}
                ):
                    continue
                tasks.append((src, dest, direction))
        if not tasks:
            raise ValueError(f"No valid failed tasks found in CSV: {csv_path}")
        return tasks

    def log_task_failure(self, worker_id, task, phase, attempt, error_message):
        should_print, error_text = self.error_recorder.record(
            worker_id, task, phase, attempt, error_message
        )
        if should_print:
            self.tprint(
                f"[!] Worker-{worker_id} {phase} failed (attempt {attempt}): "
                f"{os.path.basename(task[0])} -> {error_text}"
            )
        elif self.error_recorder.suppressed_errors == 1:
            self.tprint(
                f"[!] Too many errors. Further details are suppressed on console and written to: "
                f"{self.error_recorder.log_path}"
            )

    def log_final_failed_task(self, worker_id, task, final_attempt, error_message):
        if self.failed_task_recorder:
            self.failed_task_recorder.record(
                worker_id, task, final_attempt, error_message
            )

    def get_local_md5(self, filepath):
        hash_md5 = hashlib.md5()
        try:
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception:
            return None

    def get_remote_md5(self, ssh, remotepath):
        try:
            cmd = f"md5sum {shlex.quote(remotepath)}"
            stdin, stdout, stderr = ssh.exec_command(cmd)
            output = stdout.read().decode().strip()
            if output and " " in output:
                return output.split()[0]
        except:
            pass
        return None

    def ensure_remote_dir(self, sftp, remote_dir):
        if not remote_dir or remote_dir == "/":
            return
        try:
            sftp.stat(remote_dir)
        except IOError:
            parent = posixpath.dirname(remote_dir)
            self.ensure_remote_dir(sftp, parent)
            try:
                sftp.mkdir(remote_dir)
            except IOError:
                pass

    def resolve_paths(self):
        tasks = []
        direction = self.config["direction"]
        for item in self.config["sync_items"]:
            if "src" not in item:
                continue
            src_raw = item["src"]
            dest_raw = item.get("dest", "")
            if direction == "Client2Server":
                is_local_abs = os.path.isabs(src_raw) or (
                    len(src_raw) > 1 and src_raw[1] == ":"
                )
                local_src = (
                    src_raw
                    if is_local_abs
                    else os.path.join(
                        self.config.get("default_local_base", ""), src_raw
                    )
                )
                if not dest_raw:
                    remote_dest = posixpath.join(
                        self.config.get("default_remote_base", ""),
                        os.path.basename(local_src),
                    )
                else:
                    remote_dest = (
                        dest_raw
                        if dest_raw.startswith("/")
                        else posixpath.join(
                            self.config.get("default_remote_base", ""), dest_raw
                        )
                    )
                if os.path.isfile(local_src):
                    tasks.append(
                        self._parse_file_mapping(
                            local_src, remote_dest, direction, dest_raw
                        )
                    )
                elif os.path.isdir(local_src):
                    tasks.extend(
                        self._parse_dir_mapping(
                            local_src, remote_dest, dest_raw, direction
                        )
                    )
                else:
                    self.tprint(f"[-] Local source not found: {local_src}")
            elif direction == "Server2Client":
                remote_src = (
                    src_raw
                    if src_raw.startswith("/")
                    else posixpath.join(
                        self.config.get("default_remote_base", ""), src_raw
                    )
                )
                if not dest_raw:
                    local_dest = os.path.join(
                        self.config.get("default_local_base", ""),
                        posixpath.basename(remote_src),
                    )
                else:
                    is_local_abs = os.path.isabs(dest_raw) or (
                        len(dest_raw) > 1 and dest_raw[1] == ":"
                    )
                    local_dest = (
                        dest_raw
                        if is_local_abs
                        else os.path.join(
                            self.config.get("default_local_base", ""), dest_raw
                        )
                    )
                try:
                    mode = self.main_sftp.stat(remote_src).st_mode
                    if stat.S_ISDIR(mode):
                        tasks.extend(
                            self._parse_dir_mapping(
                                remote_src, local_dest, dest_raw, direction
                            )
                        )
                    else:
                        tasks.append(
                            self._parse_file_mapping(
                                remote_src, local_dest, direction, dest_raw
                            )
                        )
                except IOError:
                    self.tprint(f"[-] Remote source not found: {remote_src}")
        return tasks

    def _parse_file_mapping(self, src, dest, direction, raw_dest):
        if raw_dest and (raw_dest.endswith("/") or raw_dest.endswith("\\")):
            if direction == "Client2Server":
                dest = posixpath.join(dest, os.path.basename(src))
            else:
                dest = os.path.join(dest, posixpath.basename(src))
        return (src, dest, direction)

    def _parse_dir_mapping(self, src_dir, dest_dir, raw_dest, direction):
        tasks = []
        if raw_dest and (raw_dest.endswith("/") or raw_dest.endswith("\\")):
            if direction == "Client2Server":
                dest_dir = posixpath.join(dest_dir, os.path.basename(src_dir))
            else:
                dest_dir = os.path.join(dest_dir, posixpath.basename(src_dir))
        if direction == "Client2Server":
            for root, _, files in os.walk(src_dir):
                for file in files:
                    full_src = os.path.join(root, file)
                    rel_path = os.path.relpath(full_src, src_dir).replace(os.sep, "/")
                    full_dest = posixpath.join(dest_dir, rel_path)
                    tasks.append((full_src, full_dest, direction))
        else:

            def _walk_remote(current_remote_dir):
                try:
                    for entry in self.main_sftp.listdir_attr(current_remote_dir):
                        r_path = posixpath.join(current_remote_dir, entry.filename)
                        if stat.S_ISDIR(entry.st_mode):
                            _walk_remote(r_path)
                        else:
                            rel_path = posixpath.relpath(r_path, src_dir)
                            l_path = os.path.join(
                                dest_dir, rel_path.replace("/", os.sep)
                            )
                            tasks.append((r_path, l_path, direction))
                except IOError:
                    pass

            _walk_remote(src_dir)
        return tasks

    def _sync_single_file(self, task):
        src, dest, direction = task
        ssh, sftp = self.pool.get_connection()
        try:
            local_path = src if direction == "Client2Server" else dest
            remote_path = dest if direction == "Client2Server" else src
            mode = "wb"
            resume_offset = 0
            transfer_needed = True
            src_size, src_mtime = 0, 0
            dest_size, dest_mtime = 0, 0
            dest_exists = False
            if direction == "Client2Server":
                src_size = os.path.getsize(local_path)
                src_mtime = int(os.path.getmtime(local_path))
                try:
                    r_stat = sftp.stat(remote_path)
                    dest_size, dest_mtime = r_stat.st_size, r_stat.st_mtime
                    dest_exists = True
                except:
                    pass
            else:
                r_stat = sftp.stat(src)
                src_size, src_mtime = r_stat.st_size, r_stat.st_mtime
                if os.path.exists(local_path):
                    dest_size = os.path.getsize(local_path)
                    dest_mtime = int(os.path.getmtime(local_path))
                    dest_exists = True
            if dest_exists:
                policy = self.config.get("conflict_policy", "fast")
                if policy == "skip":
                    transfer_needed = False
                elif policy == "fast":
                    if src_size == dest_size and abs(src_mtime - dest_mtime) <= 2:
                        transfer_needed = False
                    elif 0 < dest_size < src_size:
                        resume_offset = dest_size
                        mode = "ab"
                elif policy == "hash":
                    if 0 < dest_size < src_size:
                        resume_offset = dest_size
                        mode = "ab"
                    elif src_size == dest_size:
                        if direction == "Client2Server":
                            r_md5 = self.get_remote_md5(ssh, remote_path)
                            l_md5 = self.get_local_md5(local_path)
                        else:
                            r_md5 = self.get_remote_md5(ssh, src)
                            l_md5 = self.get_local_md5(local_path)
                        if r_md5 and l_md5 and r_md5 == l_md5:
                            transfer_needed = False
            if transfer_needed:
                if direction == "Client2Server":
                    parent_dir = posixpath.dirname(remote_path)
                    self.ensure_remote_dir(sftp, parent_dir)
                    self.upload_file(
                        local_path, remote_path, sftp, resume_offset, mode, src_size
                    )
                    sftp.utime(remote_path, (src_mtime, src_mtime))
                else:
                    os.makedirs(os.path.dirname(local_path), exist_ok=True)
                    self.download_file(
                        src, local_path, sftp, resume_offset, mode, src_size
                    )
                    os.utime(local_path, (src_mtime, src_mtime))
                return True, "Transferred"
            else:
                return True, "Skipped"
        except Exception as e:
            return False, str(e)
        finally:
            self.pool.return_connection((ssh, sftp))

    def upload_file(self, local_path, remote_path, sftp, offset, mode, total_size):
        chunk_size = 65536
        remote_mode = "w" if mode == "wb" else "a"
        slot = self.pbar_manager.acquire_slot()
        name = os.path.basename(local_path)
        display_name = (name[:16] + "..") if len(name) > 18 else name
        try:
            with open(local_path, "rb") as fl:
                fl.seek(offset)
                with sftp.open(remote_path, remote_mode) as fr:
                    if mode == "wb":
                        fr.set_pipelined(True)
                    with tqdm(
                        total=total_size,
                        initial=offset,
                        desc=f"[{slot}] UP {display_name:<18}",
                        unit="B",
                        unit_scale=True,
                        unit_divisor=1024,
                        position=slot,
                        leave=False,
                    ) as pbar:
                        while True:
                            data = fl.read(chunk_size)
                            if not data:
                                break
                            fr.write(data)
                            pbar.update(len(data))
        finally:
            self.pbar_manager.release_slot(slot)

    def download_file(self, remote_path, local_path, sftp, offset, mode, total_size):
        chunk_size = 65536
        slot = self.pbar_manager.acquire_slot()
        name = os.path.basename(remote_path)
        display_name = (name[:16] + "..") if len(name) > 18 else name
        try:
            with sftp.open(remote_path, "rb") as fr:
                fr.seek(offset)
                with open(local_path, mode) as fl:
                    with tqdm(
                        total=total_size,
                        initial=offset,
                        desc=f"[{slot}] DL {display_name:<18}",
                        unit="B",
                        unit_scale=True,
                        unit_divisor=1024,
                        position=slot,
                        leave=False,
                    ) as pbar:
                        while True:
                            data = fr.read(chunk_size)
                            if not data:
                                break
                            fl.write(data)
                            pbar.update(len(data))
        finally:
            self.pbar_manager.release_slot(slot)

    def _process_worker_tasks(self, worker_id, tasks, pbar):
        retry_rounds = max(0, int(self.config.get("retry_rounds", 1)))
        failed_tasks = []
        for task in tasks:
            success, msg = self._sync_single_file(task)
            if success:
                self.update_result_counts(msg)
                pbar.update(1)
            else:
                self.log_task_failure(worker_id, task, "initial", 1, msg)
                failed_tasks.append((task, msg))
        remaining_tasks = failed_tasks
        for retry_index in range(1, retry_rounds + 1):
            if not remaining_tasks:
                break
            self.record_retry(len(remaining_tasks))
            self.tprint(
                f"[*] Worker-{worker_id} starting retry round {retry_index} for {len(remaining_tasks)} failed files..."
            )
            next_round_tasks = []
            for task, _last_error in remaining_tasks:
                success, msg = self._sync_single_file(task)
                if success:
                    self.update_result_counts(msg)
                    pbar.update(1)
                else:
                    self.log_task_failure(
                        worker_id, task, "retry", retry_index + 1, msg
                    )
                    next_round_tasks.append((task, msg))
            remaining_tasks = next_round_tasks
        final_attempt = retry_rounds + 1
        for task, last_error in remaining_tasks:
            self.log_final_failed_task(worker_id, task, final_attempt, last_error)
            self.update_result_counts("Failed")
            pbar.update(1)

    def run(self):
        self.connect_main()
        error_log_path = self.setup_error_recorder()
        failed_tasks_path = self.setup_failed_task_recorder()
        failed_tasks_input_path = self.get_failed_tasks_input_path()
        if failed_tasks_input_path:
            self.tprint(f"[*] Loading failed task list from: {failed_tasks_input_path}")
            tasks = self.load_failed_tasks_from_csv(failed_tasks_input_path)
        else:
            self.tprint("[*] Parsing paths and generating tasks...")
            tasks = self.resolve_paths()
        if not tasks:
            self.tprint("[!] No files found to sync.")
            self.close()
            return
        worker_count = max(1, int(self.config.get("workers", 8)))
        retry_rounds = max(0, int(self.config.get("retry_rounds", 1)))
        task_buckets = self.split_tasks_for_workers(tasks, worker_count)
        self.tprint(
            f"[*] Found {len(tasks)} files. Syncing with {worker_count} threads "
            f"(Policy: {self.config['conflict_policy']}, Retry rounds: {retry_rounds})..."
        )
        # position=0 分配给全局进度条，其它进程占据下方位置
        with tqdm(
            total=len(tasks),
            desc="Total Overall Progress  ",
            unit="file",
            position=0,
            leave=True,
        ) as pbar:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = []
                for worker_id, bucket in enumerate(task_buckets, start=1):
                    if not bucket:
                        continue
                    futures.append(
                        executor.submit(
                            self._process_worker_tasks, worker_id, bucket, pbar
                        )
                    )
                for future in futures:
                    future.result()
        total_errors = self.error_recorder.total_errors if self.error_recorder else 0
        suppressed_errors = (
            self.error_recorder.suppressed_errors if self.error_recorder else 0
        )
        total_failed_tasks = (
            self.failed_task_recorder.total_failed_tasks
            if self.failed_task_recorder
            else 0
        )
        if self.error_recorder:
            self.error_recorder.close()
            self.error_recorder = None
        if self.failed_task_recorder:
            self.failed_task_recorder.close()
            self.failed_task_recorder = None
        if total_errors == 0 and os.path.exists(error_log_path):
            try:
                os.remove(error_log_path)
            except OSError:
                pass
        if total_failed_tasks == 0 and os.path.exists(failed_tasks_path):
            try:
                os.remove(failed_tasks_path)
            except OSError:
                pass
        self.close()
        self.tprint(
            f"\n[*] Finished. Transferred: {self.transferred}, Skipped: {self.skipped}, "
            f"Failed: {self.failed}, Retried files: {self.retried}"
        )
        if total_errors > 0:
            self.tprint(
                f"[*] Error details written to: {error_log_path} "
                f"(total error events: {total_errors}, "
                f"suppressed on console: {suppressed_errors})"
            )
        if total_failed_tasks > 0:
            self.tprint(
                f"[*] Final failed task list written to: {failed_tasks_path} "
                f"(final failed files: {total_failed_tasks})"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Multi-threaded SFTP Sync Tool (Modern Edition)"
    )
    parser.add_argument(
        "-c", "--config", type=str, help="从指定的 JSON 文件加载配置并运行"
    )
    parser.add_argument(
        "-e", "--export", type=str, help="将内置的默认配置导出为一个 JSON 文件"
    )
    parser.add_argument(
        "--retry-failed-csv",
        type=str,
        help="读取上次失败任务 CSV，仅对失败文件再次同步",
    )
    args = parser.parse_args()
    # 1. 如果指定了导出配置
    if args.export:
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(CONFIG, f, indent=4, ensure_ascii=False)
        print(f"[*] Default config successfully exported to: {args.export}")
        sys.exit(0)
    # 2. 如果指定了加载配置
    if args.config:
        if not os.path.exists(args.config):
            print(f"[-] Config file '{args.config}' not found.")
            sys.exit(1)
        with open(args.config, "r", encoding="utf-8") as f:
            try:
                loaded_config = json.load(f)
            except json.JSONDecodeError as e:
                print(f"[-] Failed to parse JSON config: {e}")
                sys.exit(1)
        # 强制格式校验
        if "ssh" not in loaded_config or "sync_items" not in loaded_config:
            print("[-] Invalid Config: Must contain 'ssh' and 'sync_items' keys.")
            sys.exit(1)
        active_config = loaded_config
        print(f"[*] Successfully loaded config from: {args.config}")
    else:
        # 没有指定则走代码内嵌的字典
        active_config = CONFIG
    if args.retry_failed_csv:
        active_config["failed_tasks_input_path"] = args.retry_failed_csv
    # 3. 运行程序
    if not active_config.get("ssh", {}).get("host"):
        print("Please configure the script or JSON config first.")
    else:
        syncer = SyncManager(active_config)
        try:
            syncer.run()
        except KeyboardInterrupt:
            print("\n[!] Process stopped by user.")
            syncer.close()
