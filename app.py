from flask import Flask, render_template, request, jsonify, send_from_directory, Response
import json
import os
import requests
import uuid
import base64
from datetime import datetime
import time

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['TEMPLATES_FOLDER'] = 'templates'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

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
        result = response.json()
        # ComfyUI 直接返回 {"prompt_id": "xxx"} 或包含错误信息
        if response.status_code != 200:
            return {'error': f'HTTP {response.status_code}: {result}'}
        return result
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

if __name__ == '__main__':
    # 确保必要目录存在
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['TEMPLATES_FOLDER'], exist_ok=True)
    
    print(f"ComfyUI URL: {COMFYUI_URL}")
    print("Starting server...")
    app.run(host='0.0.0.0', port=5000, debug=True)
