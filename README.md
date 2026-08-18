# ComfyUI Web Interface

一个专业的本地 ComfyUI 生图网站，支持动态加载工作流模板。

## 功能特点

- 📁 **动态模板加载**：从 `templates/` 文件夹自动读取 JSON 工作流模板（类似 SillyTavern）
- 🎨 **三种预设模板**：基础文生图、图生图、高级放大
- ⚙️ **参数调节**：支持提示词、种子、步数、CFG、尺寸、重绘幅度等
- 🖼️ **图片上传**：支持拖拽上传，用于图生图和放大工作流
- 🔄 **实时连接检测**：自动检测 ComfyUI 服务状态
- 📊 **结果展示**：自动生成结果预览和下载功能
- 🎯 **智能节点识别**：自动识别并更新工作流中的 CLIPTextEncode、KSampler 等节点

## 项目结构

```
/workspace
├── app.py                      # Flask 后端主程序
├── templates/                  # HTML 模板和工作流 JSON 文件
│   ├── index.html             # 前端页面
│   ├── text_to_image_basic.json  # 基础文生图模板
│   ├── image_to_image.json       # 图生图模板
│   └── advanced_upscale.json     # 高级放大模板
├── static/                     # 静态资源
│   ├── css/
│   │   └── style.css          # 样式文件
│   └── js/
│       └── app.js             # 前端逻辑
└── uploads/                    # 上传图片临时存储
```

## 安装与运行

### 1. 安装依赖

```bash
pip install flask requests
```

### 2. 确保 ComfyUI 正在运行

默认地址：`http://127.0.0.1:8188`

如需修改地址，设置环境变量：
```bash
export COMFYUI_URL=http://your-comfyui-host:8188
```

### 3. 启动网站

```bash
python app.py
```

访问：http://localhost:5000

## 添加自定义模板

1. 在 ComfyUI 中导出工作流为 JSON 格式（API 格式）
2. 将 JSON 文件放入 `templates/` 文件夹
3. 建议包含以下结构：

```json
{
  "name": "你的模板名称",
  "description": "模板描述",
  "workflow": {
    // ComfyUI API 格式的工作流数据
  }
}
```

4. 刷新网页，新模板将自动出现在下拉列表中

## 模板格式说明

支持的 JSON 结构有两种：

### 格式 A（推荐）
```json
{
  "name": "模板名称",
  "description": "模板描述",
  "workflow": {
    "3": { "class_type": "KSampler", ... },
    "4": { "class_type": "CheckpointLoaderSimple", ... }
  }
}
```

### 格式 B（直接工作流）
```json
{
  "3": { "class_type": "KSampler", ... },
  "4": { "class_type": "CheckpointLoaderSimple", ... }
}
```

系统会自动识别两种格式。

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 主页 |
| `/api/templates` | GET | 获取所有模板（支持 `?refresh=true` 强制刷新） |
| `/api/generate` | POST | 提交生成任务 |
| `/api/history/<prompt_id>` | GET | 查询生成历史 |
| `/api/image` | GET | 获取生成的图片 |
| `/api/check_connection` | GET | 检查 ComfyUI 连接状态 |

## 注意事项

- 上传的图片会临时保存在 `uploads/` 文件夹
- 模板文件修改后，点击刷新按钮或等待 5 秒缓存过期即可生效
- 确保 ComfyUI 已加载所需模型，否则会生成失败

## 技术栈

- **后端**: Python + Flask
- **前端**: HTML5 + CSS3 + Vanilla JavaScript
- **API**: ComfyUI Native API
