// ComfyUI Web Interface - 前端逻辑

// 全局状态
let currentWorkflow = null;
let currentTemplate = null;
let pollInterval = null;
let isGenerating = false;

// DOM 元素
const templateSelect = document.getElementById('templateSelect');
const refreshTemplatesBtn = document.getElementById('refreshTemplates');
const templateDescription = document.getElementById('templateDescription');
const promptInput = document.getElementById('prompt');
const negativePromptInput = document.getElementById('negativePrompt');
const seedInput = document.getElementById('seed');
const stepsInput = document.getElementById('steps');
const cfgInput = document.getElementById('cfg');
const widthInput = document.getElementById('width');
const heightInput = document.getElementById('height');
const denoiseInput = document.getElementById('denoise');
const imageUpload = document.getElementById('imageUpload');
const uploadArea = document.getElementById('uploadArea');
const uploadPreview = document.getElementById('uploadPreview');
const generateBtn = document.getElementById('generateBtn');
const cancelBtn = document.getElementById('cancelBtn');
const progressInfo = document.getElementById('progressInfo');
const resultContainer = document.getElementById('resultContainer');
const connectionStatus = document.getElementById('connectionStatus');

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    loadTemplates();
    checkConnection();
    setupEventListeners();
    randomizeSeed();
});

// 设置事件监听器
function setupEventListeners() {
    // 模板选择
    templateSelect.addEventListener('change', onTemplateChange);
    refreshTemplatesBtn.addEventListener('click', loadTemplates);

    // 图片上传
    imageUpload.addEventListener('change', handleImageUpload);
    
    // 移除上传的图片按钮
    const removeUploadBtn = document.getElementById('removeUpload');
    if (removeUploadBtn) {
        removeUploadBtn.addEventListener('click', removeUploadedImage);
    }
    
    // 点击上传区域触发文件选择
    uploadArea.addEventListener('click', (e) => {
        if (e.target !== uploadPreview && e.target.id !== 'removeUpload') {
            imageUpload.click();
        }
    });
    
    // 拖拽上传
    uploadArea.addEventListener('dragover', handleDragOver);
    uploadArea.addEventListener('dragleave', handleDragLeave);
    uploadArea.addEventListener('drop', handleDrop);

    // 生成按钮
    generateBtn.addEventListener('click', startGeneration);
    cancelBtn.addEventListener('click', cancelGeneration);
}

// 加载模板列表
async function loadTemplates() {
    try {
        const response = await fetch('/api/templates?refresh=true');
        const data = await response.json();
        
        // 清空现有选项
        templateSelect.innerHTML = '<option value="">-- 请选择模板 --</option>';
        
        if (data.templates && data.templates.length > 0) {
            data.templates.forEach((template, index) => {
                const option = document.createElement('option');
                option.value = index;
                option.textContent = template.name || template.filename || `模板 ${index + 1}`;
                templateSelect.appendChild(option);
            });
            console.log(`已加载 ${data.templates.length} 个模板`);
        } else {
            showToast('未找到任何模板，请在 templates 文件夹中添加 JSON 文件', 'info');
        }
    } catch (error) {
        console.error('加载模板失败:', error);
        showToast('加载模板失败：' + error.message, 'error');
    }
}

// 模板变更处理
function onTemplateChange() {
    const selectedIndex = templateSelect.value;
    
    if (selectedIndex === '') {
        currentTemplate = null;
        currentWorkflow = null;
        templateDescription.textContent = '';
        return;
    }
    
    // 获取选中的模板数据
    fetch('/api/templates')
        .then(response => response.json())
        .then(data => {
            currentTemplate = data.templates[selectedIndex];
            currentWorkflow = JSON.parse(JSON.stringify(currentTemplate.workflow)); // 深拷贝
            
            // 显示描述
            templateDescription.textContent = currentTemplate.description || '无描述';
            
            // 根据模板类型调整 UI
            adjustUIForTemplate(currentTemplate);
        })
        .catch(error => {
            console.error('获取模板详情失败:', error);
            showToast('获取模板详情失败', 'error');
        });
}

// 根据模板类型调整 UI
function adjustUIForTemplate(template) {
    const hasLoadImage = checkTemplateHasNode(template.workflow, 'LoadImage');
    const hasEmptyLatent = checkTemplateHasNode(template.workflow, 'EmptyLatentImage');
    
    // 如果有 LoadImage 节点，显示上传区域
    uploadArea.style.display = hasLoadImage ? 'flex' : 'none';
    
    // 如果没有 EmptyLatentImage 节点，隐藏尺寸设置
    const widthGroup = widthInput.closest('.form-group');
    const heightGroup = heightInput.closest('.form-group');
    if (!hasEmptyLatent) {
        widthGroup.style.display = 'none';
        heightGroup.style.display = 'none';
    } else {
        widthGroup.style.display = 'flex';
        heightGroup.style.display = 'flex';
    }
}

// 检查工作流是否包含特定类型的节点
function checkTemplateHasNode(workflow, classType) {
    for (const nodeId in workflow) {
        if (workflow[nodeId].class_type === classType) {
            return true;
        }
    }
    return false;
}

// 图片上传处理
let uploadedImageFile = null;

function handleDragOver(e) {
    e.preventDefault();
    uploadArea.classList.add('drag-over');
}

function handleDragLeave(e) {
    e.preventDefault();
    uploadArea.classList.remove('drag-over');
}

function handleDrop(e) {
    e.preventDefault();
    uploadArea.classList.remove('drag-over');
    
    const files = e.dataTransfer.files;
    if (files.length > 0) {
        imageUpload.files = files;
        processImageFile(files[0]);
    }
}

function handleImageUpload(e) {
    const files = e.target.files;
    if (files.length > 0) {
        processImageFile(files[0]);
    }
}

function processImageFile(file) {
    if (!file.type.startsWith('image/')) {
        showToast('请选择图片文件', 'error');
        return;
    }
    
    uploadedImageFile = file;
    const reader = new FileReader();
    reader.onload = (e) => {
        uploadPreview.src = e.target.result;
        uploadPreview.style.display = 'block';
        document.querySelector('.upload-content').style.display = 'none';
        document.getElementById('removeUpload').style.display = 'flex';
    };
    reader.readAsDataURL(file);
}

// 移除上传的图片
function removeUploadedImage() {
    uploadedImageFile = null;
    imageUpload.value = '';
    uploadPreview.src = '';
    uploadPreview.style.display = 'none';
    document.querySelector('.upload-content').style.display = 'block';
    document.getElementById('removeUpload').style.display = 'none';
}

// 随机种子
function randomizeSeed() {
    seedInput.value = Math.floor(Math.random() * 2147483647);
}

// 检查连接状态
async function checkConnection() {
    try {
        const response = await fetch('/api/check_connection');
        const data = await response.json();
        
        const indicator = connectionStatus.querySelector('.status-indicator');
        const text = connectionStatus.querySelector('.status-text');
        
        if (data.connected) {
            indicator.className = 'status-indicator connected';
            text.textContent = 'ComfyUI 已连接';
        } else {
            indicator.className = 'status-indicator disconnected';
            text.textContent = 'ComfyUI 未连接';
            showToast('无法连接到 ComfyUI，请确保其正在运行', 'error');
        }
    } catch (error) {
        const indicator = connectionStatus.querySelector('.status-indicator');
        const text = connectionStatus.querySelector('.status-text');
        indicator.className = 'status-indicator disconnected';
        text.textContent = '连接失败';
    }
}

// 开始生成
async function startGeneration() {
    if (!currentWorkflow) {
        showToast('请先选择一个工作流模板', 'error');
        return;
    }
    
    isGenerating = true;
    generateBtn.disabled = true;
    cancelBtn.disabled = false;
    progressInfo.style.display = 'block';
    
    // 准备工作流数据
    const workflowData = prepareWorkflowData();
    
    try {
        const response = await fetch('/api/generate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(workflowData)
        });
        
        const result = await response.json();
        
        if (result.error) {
            throw new Error(result.error);
        }
        
        showToast('任务已提交到 ComfyUI', 'success');
        
        // 开始轮询结果
        pollForResult(result.prompt_id, result.client_id);
        
    } catch (error) {
        console.error('生成失败:', error);
        showToast('生成失败：' + error.message, 'error');
        resetGenerationState();
    }
}

// 准备工作流数据
function prepareWorkflowData() {
    const data = {
        workflow: currentWorkflow,
        prompt: promptInput.value,
        negative_prompt: negativePromptInput.value,
        seed: parseInt(seedInput.value),
        steps: parseInt(stepsInput.value),
        cfg: parseFloat(cfgInput.value),
        width: parseInt(widthInput.value),
        height: parseInt(heightInput.value),
        denoise: parseFloat(denoiseInput.value)
    };
    
    // 添加上传的图片（如果有）
    if (uploadedImageFile && uploadPreview.src && uploadPreview.style.display !== 'none') {
        data.image_data = uploadPreview.src;
    }
    
    return data;
}

// 轮询生成结果
function pollForResult(promptId, clientId) {
    let attempts = 0;
    const maxAttempts = 300; // 5 分钟超时

    console.log(`开始轮询结果，prompt_id: ${promptId}`);

    pollInterval = setInterval(async () => {
        attempts++;

        if (attempts >= maxAttempts) {
            clearInterval(pollInterval);
            showToast('生成超时', 'error');
            resetGenerationState();
            return;
        }

        try {
            const response = await fetch(`/api/history/${promptId}`);
            const data = await response.json();

            console.log(`轮询尝试 ${attempts}:`, data);

            if (data.error) {
                // 可能还在处理中，继续轮询
                return;
            }

            // 检查是否有 images 数组或者 history 中有输出
            if (data.images && data.images.length > 0) {
                // 生成完成
                clearInterval(pollInterval);
                displayResults(data.images);
                resetGenerationState();
            } else if (Object.keys(data).length > 0 && !data.images) {
                // 可能有数据但格式不同，检查是否包含 outputs
                console.log('检测到历史数据但无 images 数组:', data);
            }
        } catch (error) {
            console.error('轮询失败:', error);
        }
    }, 1000); // 每秒轮询一次
}


// 显示结果
function displayResults(images) {
    resultContainer.innerHTML = '';
    
    images.forEach((img, index) => {
        const imgUrl = `/api/image?filename=${encodeURIComponent(img.filename)}&subfolder=${encodeURIComponent(img.subfolder || '')}&type=${encodeURIComponent(img.type || 'output')}`;
        
        const imgElement = document.createElement('img');
        imgElement.src = imgUrl;
        imgElement.className = 'result-image';
        imgElement.alt = `生成结果 ${index + 1}`;
        
        const actionsDiv = document.createElement('div');
        actionsDiv.className = 'result-actions';
        
        const downloadBtn = document.createElement('button');
        downloadBtn.className = 'btn btn-secondary';
        downloadBtn.textContent = '⬇️ 下载';
        downloadBtn.onclick = () => downloadImage(imgUrl, `comfyui_result_${index + 1}.png`);
        
        actionsDiv.appendChild(downloadBtn);
        
        const container = document.createElement('div');
        container.style.marginBottom = '20px';
        container.appendChild(imgElement);
        container.appendChild(actionsDiv);
        
        resultContainer.appendChild(container);
    });
    
    showToast(`生成完成！共 ${images.length} 张图片`, 'success');
}

// 下载图片
function downloadImage(url, filename) {
    fetch(url)
        .then(response => response.blob())
        .then(blob => {
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(link.href);
        })
        .catch(error => {
            console.error('下载失败:', error);
            showToast('下载失败', 'error');
        });
}

// 取消生成（目前只是重置状态，ComfyUI 队列中的任务仍会继续）
function cancelGeneration() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
    resetGenerationState();
    showToast('已取消等待', 'info');
}

// 重置生成状态
function resetGenerationState() {
    isGenerating = false;
    generateBtn.disabled = false;
    cancelBtn.disabled = true;
    progressInfo.style.display = 'none';
}

// Toast 通知 - 现代化版本
function showToast(message, type = 'info') {
    let container = document.getElementById('toastContainer');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toastContainer';
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    
    // 图标映射
    const icons = {
        success: `<svg class="toast-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M22 11.08V12a10 10 0 11-5.93-9.14" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><polyline points="22,4 12,14.01 9,11.01" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
        error: `<svg class="toast-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2"/><line x1="15" y1="9" x2="9" y2="15" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="9" y1="9" x2="15" y2="15" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>`,
        info: `<svg class="toast-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2"/><line x1="12" y1="16" x2="12" y2="12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="12" y1="8" x2="12.01" y2="8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>`,
        warning: `<svg class="toast-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><line x1="12" y1="9" x2="12" y2="13" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="12" y1="17" x2="12.01" y2="17" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>`
    };
    
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `${icons[type] || icons.info}<span class="toast-message">${message}</span>`;
    
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'slideInRight 0.4s cubic-bezier(0.19, 1, 0.22, 1) reverse';
        setTimeout(() => toast.remove(), 400);
    }, 3000);
}

// 暴露给全局的函数（用于 HTML onclick）
window.randomizeSeed = randomizeSeed;
window.removeUploadedImage = removeUploadedImage;
