from flask import Flask, render_template, request, jsonify, send_from_directory, Response
import json
import os
import re
import requests
import subprocess
import uuid
import base64
from datetime import datetime
from pathlib import Path
import threading
import time

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['TEMPLATES_FOLDER'] = 'templates'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# 项目根目录与设置文件
BASE_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = BASE_DIR / 'settings.json'
_update_lock = threading.Lock()


def load_settings():
    """加载设置文件"""
    settings = {
        'auto_update': False,          # 是否开启定时自动拉取
        'update_interval_minutes': 30, # 自动拉取间隔（分钟）
        'github_repo_url': '',         # GitHub 仓库地址（可选，留空则使用当前 origin）
        'github_branch': ''            # 分支（可选，留空则使用当前分支）
    }
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                settings.update(json.load(f))
    except Exception as e:
        print(f'Error loading settings: {e}')
    return settings


def save_settings(settings):
    """保存设置文件"""
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def run_git(args, timeout=120):
    """在项目根目录执行 git 命令，返回 (returncode, stdout+stderr)"""
    try:
        result = subprocess.run(
            ['git'] + args,
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=timeout
        )
        output = ((result.stdout or '') + (result.stderr or '')).strip()
        return result.returncode, output
    except FileNotFoundError:
        return -1, '未找到 git 命令，请确认已安装 Git 并加入 PATH'
    except subprocess.TimeoutExpired:
        return -1, 'git 命令执行超时'
    except Exception as e:
        return -1, str(e)


def normalize_repo_url(url):
    """把 GitHub 页面/仓库地址规范化为可 clone/pull 的 URL"""
    url = (url or '').strip().rstrip('/')
    if not url:
        return ''
    m = re.match(r'^https?://github\.com/([^/\s]+)/([^/\s]+?)(?:\.git)?/?$', url)
    if m:
        return f'https://github.com/{m.group(1)}/{m.group(2)}.git'
    if url.startswith('git@github.com:'):
        return url if url.endswith('.git') else url + '.git'
    if url.startswith(('http://', 'https://', 'git@', 'ssh://')):
        return url
    return ''


def get_current_remote_url():
    code, out = run_git(['config', '--get', 'remote.origin.url'])
    return out if code == 0 else ''


def do_pull():
    """执行一次 GitHub 仓库更新拉取，返回结果字典"""
    settings = load_settings()
    target_url = normalize_repo_url(settings.get('github_repo_url', '')) or get_current_remote_url()
    if not target_url:
        return {'success': False, 'message': '未配置 GitHub 仓库地址，且当前目录没有 origin 远程'}

    branch = (settings.get('github_branch') or '').strip()

    code, cur_branch_out = run_git(['rev-parse', '--abbrev-ref', 'HEAD'])
    current_branch = cur_branch_out if code == 0 else ''
    if not branch:
        branch = current_branch if current_branch and current_branch != 'HEAD' else 'main'

    rc, ls_out = run_git(['ls-remote', '--heads', target_url, branch], timeout=30)
    if rc != 0:
        return {'success': False, 'message': f'无法访问远程仓库：{ls_out}'}
    if not ls_out.strip():
        return {'success': False, 'message': f'远程仓库不存在分支 {branch}，请检查仓库地址和分支名'}

    has_origin = run_git(['remote', 'get-url', 'origin'])[0] == 0
    if has_origin:
        run_git(['remote', 'set-url', 'origin', target_url])
    else:
        rc, out = run_git(['remote', 'add', 'origin', target_url])
        if rc != 0:
            return {'success': False, 'message': f'添加远程仓库失败：{out}'}

    rc, out = run_git(['fetch', 'origin', branch])
    if rc != 0:
        return {'success': False, 'message': f'fetch 失败：{out}'}

    rc, local_sha = run_git(['rev-parse', 'HEAD'])
    rc2, remote_sha = run_git(['rev-parse', 'FETCH_HEAD'])
    if rc == 0 and rc2 == 0 and local_sha == remote_sha:
        return {'success': True, 'up_to_date': True,
                'message': f'已是最新版本（{branch} @ {local_sha[:7]}），无需更新'}

    # 本地有未提交的改动时先自动暂存，避免 pull 失败丢改动
    dirty = run_git(['status', '--porcelain'])[1] != ''
    if dirty:
        rc, out = run_git(['stash', 'push', '-m', 'auto-update 自动暂存本地改动'])
        if rc != 0:
            return {'success': False, 'message': f'本地存在未提交改动且暂存失败：{out}'}

    if current_branch == branch:
        rc, out = run_git(['pull', '--ff-only', 'origin', branch])
    else:
        rc, out = run_git(['checkout', '-B', branch, 'FETCH_HEAD'])
        if rc == 0:
            rc, out = run_git(['pull', '--ff-only', 'origin', branch])

    if rc != 0:
        msg = f'拉取更新失败：{out}'
        if dirty:
            msg += '（本地改动已保存在 git stash 中，可执行 git stash pop 恢复）'
        return {'success': False, 'message': msg}

    new_rc, new_sha = run_git(['rev-parse', 'HEAD'])
    updated_files = run_git(['diff', '--name-only', local_sha, 'HEAD'])[1] if rc == 0 and local_sha else ''
    short_sha = new_sha[:7] if (new_rc == 0 and re.match(r'^[0-9a-f]{40}$', new_sha or '')) else ''
    result = {
        'success': True,
        'up_to_date': False,
        'message': f'更新成功！已拉取 {branch} 最新代码' + (f'（{short_sha}）' if short_sha else ''),
        'updated_files': [f for f in updated_files.splitlines() if f],
    }
    if dirty:
        result['message'] += '；本地未提交的改动已暂存到 git stash'

    # 如果模板/工作流文件有变化，刷新模板缓存
    global _templates_cache, _templates_cache_time
    _templates_cache = None
    _templates_cache_time = 0

    return result


def update_log(message):
    """记录更新日志到 last_update.json"""
    log = {}
    log_file = BASE_DIR / 'last_update.json'
    try:
        if log_file.exists():
            with open(log_file, 'r', encoding='utf-8') as f:
                log = json.load(f)
    except Exception:
        log = {}
    log.setdefault('history', [])
    log['last_result'] = message
    log.setdefault('history', []).append({
        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'result': message
    })
    log['history'] = log['history'][-20:]
    try:
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f'Error writing update log: {e}')


def auto_update_worker():
    """后台线程：按设置间隔自动拉取更新"""
    while True:
        settings = load_settings()
        interval = max(int(settings.get('update_interval_minutes', 30) or 30), 1) * 60
        time.sleep(interval)
        try:
            settings = load_settings()
            if not settings.get('auto_update'):
                continue
            if not _update_lock.acquire(blocking=False):
                continue
            try:
                result = do_pull()
                update_log(result.get('message', ''))
                print('[auto-update]', result.get('message', ''))
            finally:
                _update_lock.release()
        except Exception as e:
            print(f'[auto-update] error: {e}')


threading.Thread(target=auto_update_worker, daemon=True).start()

# ComfyUI API 地址
COMFYUI_URL = os.environ.get('COMFYUI_URL', 'http://127.0.0.1:8188')

# 缓存模板数据，避免频繁读取文件
_templates_cache = None
_templates_cache_time = 0
CACHE_DURATION = 5  # 缓存5秒

def get_client_id():
    """生成客户端 ID"""
    return str(uuid.uuid4())

def load_templates(force_refresh=False):
    """从 templates 文件夹加载所有 JSON 模板（类似 SillyTavern 方式）"""
    global _templates_cache, _templates_cache_time
    
    current_time = time.time()
    
    # 如果未强制刷新且缓存有效，返回缓存数据
    if not force_refresh and _templates_cache is not None and (current_time - _templates_cache_time) < CACHE_DURATION:
        return _templates_cache
    
    templates = []
    templates_dir = app.config['TEMPLATES_FOLDER']
    
    if not os.path.exists(templates_dir):
        os.makedirs(templates_dir)
        _templates_cache = templates
        _templates_cache_time = current_time
        return templates
    
    for filename in os.listdir(templates_dir):
        if filename.endswith('.json'):
            filepath = os.path.join(templates_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    template_data = json.load(f)
                    # 保留原始数据结构，添加元信息
                    template_info = {
                        'filename': filename,
                        'name': template_data.get('name', filename.replace('.json', '')),
                        'description': template_data.get('description', ''),
                        'workflow': template_data.get('workflow', template_data)
                    }
                    templates.append(template_info)
            except Exception as e:
                print(f"Error loading template {filename}: {e}")
    
    # 按名称排序
    templates.sort(key=lambda x: x.get('name', ''))
    
    _templates_cache = templates
    _templates_cache_time = current_time
    
    return templates

def queue_prompt(prompt, client_id):
    """发送提示到 ComfyUI 队列"""
    try:
        response = requests.post(
            f'{COMFYUI_URL}/prompt',
            json={'prompt': prompt, 'client_id': client_id}
        )
        return response.json()
    except Exception as e:
        return {'error': str(e)}

def get_history(prompt_id):
    """获取生成历史"""
    try:
        response = requests.get(f'{COMFYUI_URL}/history/{prompt_id}')
        return response.json()
    except Exception as e:
        return {'error': str(e)}

def get_image(filename, subfolder, folder_type):
    """获取生成的图片"""
    try:
        params = {'filename': filename, 'subfolder': subfolder, 'type': folder_type}
        response = requests.get(f'{COMFYUI_URL}/view', params=params)
        return response.content
    except Exception as e:
        return None

@app.route('/')
def index():
    """主页"""
    return render_template('index.html')

@app.route('/api/templates', methods=['GET'])
def api_get_templates():
    """获取所有模板（支持强制刷新）"""
    force_refresh = request.args.get('refresh', 'false').lower() == 'true'
    templates = load_templates(force_refresh=force_refresh)
    return jsonify({'templates': templates})

@app.route('/api/generate', methods=['POST'])
def api_generate():
    """生成图片"""
    data = request.json
    
    if not data or 'workflow' not in data:
        return jsonify({'error': '缺少工作流数据'}), 400
    
    workflow = data['workflow']
    client_id = get_client_id()
    
    # 修改工作流中的参数 - 智能查找节点
    prompt_text = data.get('prompt')
    negative_prompt_text = data.get('negative_prompt')
    
    if prompt_text or negative_prompt_text:
        # 查找所有 CLIPTextEncode 节点
        clip_nodes = []
        for node_id, node_data in workflow.items():
            if node_data.get('class_type') == 'CLIPTextEncode':
                inputs = node_data.get('inputs', {})
                if 'text' in inputs:
                    clip_nodes.append({
                        'node_id': node_id,
                        'inputs': inputs,
                        'original_text': inputs.get('text', '')
                    })
        
        # 根据内容判断正负向提示词，并更新
        if len(clip_nodes) >= 2 and prompt_text and negative_prompt_text:
            # 尝试智能区分：通常负向提示词包含 watermark, blurry, low quality 等
            for node in clip_nodes:
                original_lower = node['original_text'].lower()
                if any(kw in original_lower for kw in ['watermark', 'blurry', 'low quality', 'ugly', 'bad']):
                    node['inputs']['text'] = negative_prompt_text
                else:
                    node['inputs']['text'] = prompt_text
        elif len(clip_nodes) >= 1:
            # 如果只有一个或无法区分，第一个设为正向
            if prompt_text:
                clip_nodes[0]['inputs']['text'] = prompt_text
            if len(clip_nodes) >= 2 and negative_prompt_text:
                clip_nodes[1]['inputs']['text'] = negative_prompt_text
    
    # 更新 KSampler 参数
    if 'seed' in data:
        for node_id, node_data in workflow.items():
            if node_data.get('class_type') == 'KSampler':
                inputs = node_data.get('inputs', {})
                if 'seed' in inputs:
                    inputs['seed'] = int(data['seed'])
    
    if 'steps' in data:
        for node_id, node_data in workflow.items():
            if node_data.get('class_type') == 'KSampler':
                inputs = node_data.get('inputs', {})
                if 'steps' in inputs:
                    inputs['steps'] = int(data['steps'])
    
    if 'cfg' in data:
        for node_id, node_data in workflow.items():
            if node_data.get('class_type') == 'KSampler':
                inputs = node_data.get('inputs', {})
                if 'cfg' in inputs:
                    inputs['cfg'] = float(data['cfg'])
    
    if 'denoise' in data:
        for node_id, node_data in workflow.items():
            if node_data.get('class_type') == 'KSampler':
                inputs = node_data.get('inputs', {})
                if 'denoise' in inputs:
                    inputs['denoise'] = float(data['denoise'])
    
    if 'width' in data and 'height' in data:
        for node_id, node_data in workflow.items():
            if node_data.get('class_type') == 'EmptyLatentImage':
                inputs = node_data.get('inputs', {})
                if 'width' in inputs and 'height' in inputs:
                    inputs['width'] = int(data['width'])
                    inputs['height'] = int(data['height'])
    
    # 处理上传的图片（如果有）
    uploaded_filename = None
    if 'image_data' in data:
        image_data = data['image_data']
        # 保存图片到 uploads 文件夹
        uploaded_filename = f"upload_{uuid.uuid4()}.png"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], uploaded_filename)
        
        # 解码 base64 图片
        if ',' in image_data:
            image_data = image_data.split(',')[1]
        
        try:
            with open(filepath, 'wb') as f:
                f.write(base64.b64decode(image_data))
            
            # 更新工作流中的 LoadImage 节点
            for node_id, node_data in workflow.items():
                if node_data.get('class_type') == 'LoadImage':
                    inputs = node_data.get('inputs', {})
                    if 'image' in inputs:
                        inputs['image'] = uploaded_filename
        except Exception as e:
            return jsonify({'error': f'处理图片失败：{str(e)}'}), 500
    
    # 发送到 ComfyUI
    result = queue_prompt(workflow, client_id)
    
    if 'error' in result:
        return jsonify(result), 500
    
    return jsonify({
        'success': True,
        'prompt_id': result.get('prompt_id'),
        'client_id': client_id,
        'message': '任务已提交到 ComfyUI 队列'
    })

@app.route('/api/history/<prompt_id>')
def api_get_history(prompt_id):
    """获取特定 prompt_id 的历史记录"""
    history = get_history(prompt_id)
    
    if 'error' in history:
        return jsonify(history), 500
    
    # 提取图片信息
    images = []
    if prompt_id in history:
        prompt_history = history[prompt_id]
        outputs = prompt_history.get('outputs', {})
        
        for node_id, output_data in outputs.items():
            if 'images' in output_data:
                for img in output_data['images']:
                    images.append({
                        'filename': img.get('filename'),
                        'subfolder': img.get('subfolder', ''),
                        'type': img.get('type', 'output')
                    })
    
    return jsonify({'images': images})

@app.route('/api/image')
def api_get_image():
    """获取图片内容"""
    filename = request.args.get('filename')
    subfolder = request.args.get('subfolder', '')
    folder_type = request.args.get('type', 'output')
    
    if not filename:
        return jsonify({'error': '缺少文件名'}), 400
    
    image_data = get_image(filename, subfolder, folder_type)
    
    if image_data is None:
        return jsonify({'error': '无法获取图片'}), 500
    
    from flask import Response
    return Response(image_data, mimetype='image/png')

@app.route('/api/check_connection')
def api_check_connection():
    """检查与 ComfyUI 的连接"""
    try:
        response = requests.get(f'{COMFYUI_URL}/system_stats', timeout=5)
        return jsonify({'connected': True, 'status': 'ok'})
    except Exception as e:
        return jsonify({'connected': False, 'error': str(e)})

@app.route('/api/settings', methods=['GET'])
def api_get_settings():
    """获取设置"""
    settings = load_settings()
    settings['current_remote'] = get_current_remote_url()
    code, branch = run_git(['rev-parse', '--abbrev-ref', 'HEAD'])
    settings['current_branch'] = branch if code == 0 else ''
    code, sha = run_git(['rev-parse', '--short', 'HEAD'])
    settings['current_commit'] = sha if code == 0 else ''
    return jsonify({'settings': settings})

@app.route('/api/settings', methods=['POST'])
def api_save_settings():
    """保存设置"""
    data = request.json or {}
    settings = load_settings()

    if 'auto_update' in data:
        settings['auto_update'] = bool(data['auto_update'])
    if 'update_interval_minutes' in data:
        try:
            interval = int(data['update_interval_minutes'])
            settings['update_interval_minutes'] = min(max(interval, 1), 1440)
        except (TypeError, ValueError):
            return jsonify({'error': '更新间隔必须是整数分钟'}), 400
    if 'github_repo_url' in data:
        url = (data['github_repo_url'] or '').strip()
        if url and not normalize_repo_url(url):
            return jsonify({'error': 'GitHub 仓库地址格式不正确，请使用 https://github.com/用户/仓库 形式'}), 400
        settings['github_repo_url'] = url
    if 'github_branch' in data:
        settings['github_branch'] = (data['github_branch'] or '').strip()

    try:
        save_settings(settings)
    except Exception as e:
        return jsonify({'error': f'保存设置失败：{e}'}), 500

    return jsonify({'success': True, 'message': '设置已保存', 'settings': settings})

@app.route('/api/update', methods=['POST'])
def api_update():
    """手动触发一次 GitHub 仓库更新拉取"""
    if not _update_lock.acquire(blocking=False):
        return jsonify({'success': False, 'message': '已有更新任务正在进行中，请稍候'}), 409
    try:
        result = do_pull()
        update_log(result.get('message', ''))
        status_code = 200 if result.get('success') else 500
        return jsonify(result), status_code
    except Exception as e:
        return jsonify({'success': False, 'message': f'更新失败：{e}'}), 500
    finally:
        _update_lock.release()

@app.route('/api/update/log')
def api_update_log():
    """查看最近一次自动/手动更新结果"""
    log_file = BASE_DIR / 'last_update.json'
    try:
        if log_file.exists():
            with open(log_file, 'r', encoding='utf-8') as f:
                return jsonify(json.load(f))
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({'last_result': '', 'history': []})

if __name__ == '__main__':
    # 确保必要目录存在
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['TEMPLATES_FOLDER'], exist_ok=True)
    
    print(f"ComfyUI URL: {COMFYUI_URL}")
    print("Starting server...")
    app.run(host='0.0.0.0', port=5000, debug=True)
