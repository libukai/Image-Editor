/**
 * AnkiIntegration.js
 * 
 * Anki 插件集成模块
 * 用于处理 Method Draw 与 Anki 的通信和交互
 */

MD.AnkiIntegration = function() {
    const self = this;
    
    // 检测是否在 Anki 环境中
    this.isAnkiEnv = false;
    this.waitingForPycmd = false;
    
    /**
     * 初始化 Anki 集成
     */
    this.init = function() {
        // 检测 pycmd 函数是否存在
        this.detectAnkiEnvironment();
        
        if (this.isAnkiEnv) {
            console.log("Anki environment detected, initializing integration...");
            this.setupAnkiBindings();
        }
    };
    
    /**
     * 检测 Anki 环境
     */
    this.detectAnkiEnvironment = function() {
        // 立即检查
        if (typeof pycmd === "function") {
            this.isAnkiEnv = true;
            return;
        }
        
        // 如果没有立即检测到，等待一段时间
        this.waitForPycmd(() => {
            this.isAnkiEnv = true;
            this.setupAnkiBindings();
        });
    };
    
    /**
     * 等待 pycmd 函数可用
     */
    this.waitForPycmd = function(callback, maxAttempts = 30) {
        let attempts = 0;
        
        const checkPycmd = () => {
            if (typeof pycmd === "function") {
                callback();
            } else if (attempts < maxAttempts) {
                attempts++;
                setTimeout(checkPycmd, 100);
            }
        };
        
        checkPycmd();
    };
    
    /**
     * 设置 Anki 相关的绑定
     */
    this.setupAnkiBindings = function() {
        // 先清空画布，确保从干净状态开始
        if (svgCanvas && typeof svgCanvas.clear === 'function') {
            svgCanvas.clear();
            this.log("Canvas cleared on initialization");
        }
        
        // 请求初始图像
        pycmd("img_src");
        
        // 重写保存功能
        this.overrideSaveFunction();
        
        // 重写导出功能
        this.overrideExportFunction();
        
        // 添加全局函数供 Anki 调用
        window.ankiAddonSetImg = this.setImage.bind(this);
        window.ankiAddonSaveImg = this.saveImage.bind(this);
    };
    
    /**
     * 设置图像
     * @param {string} data - 图像数据（base64 或 SVG 字符串）
     * @param {string} type - 图像类型（"svg" 或其他）
     */
    this.setImage = function(data, type) {
        // 清空画布，移除所有现有内容
        this.log("Clearing canvas before loading new image");
        svgCanvas.clear();
        
        if (type === "svg") {
            // 直接加载 SVG 字符串
            svgCanvas.setSvgString(data);
        } else {
            // 处理位图
            this.setRasterImage(data);
        }
    };
    
    /**
     * 设置栅格图像
     * @param {string} data - base64 编码的图像数据
     */
    this.setRasterImage = function(data) {
        const setImageDimensions = (imgWidth, imgHeight) => {
            // 清空并设置画布尺寸
            svgCanvas.clear();
            svgCanvas.setResolution(imgWidth, imgHeight);
            $("#canvas_width").val(imgWidth);
            $("#canvas_height").val(imgHeight);
            
            // 创建图像元素
            const newImage = svgCanvas.addSvgElementFromJson({
                "element": "image",
                "attr": {
                    "x": 0,
                    "y": 0,
                    "width": imgWidth,
                    "height": imgHeight,
                    "id": svgCanvas.getNextId(),
                    "style": "pointer-events:inherit"
                }
            });
            
            // 设置图像源
            svgCanvas.setHref(newImage, data);
            
            // 选择并居中图像
            svgCanvas.selectOnly([newImage]);
            svgCanvas.alignSelectedElements("m", "page");
            svgCanvas.alignSelectedElements("c", "page");
            svgCanvas.clearSelection();
            
            // 更新画布
            editor.canvas.update();
        };
        
        // 创建临时图像以获取尺寸
        const img = new Image();
        img.src = data;
        
        img.onload = function() {
            setImageDimensions(img.width, img.height);
        };
        
        // 如果图像加载失败，使用默认尺寸
        img.onerror = function() {
            console.error("Failed to load image");
            setImageDimensions(100, 100);
        };
    };
    
    /**
     * 保存图像到 Anki
     */
    this.saveImage = function() {
        // 清除选择
        svgCanvas.clearSelection();
        
        // 获取 SVG 字符串
        const svgStr = svgCanvas.getSvgString();
        
        // 发送到 Anki
        pycmd("svg_save:" + svgStr);
    };
    
    /**
     * 重写保存功能
     */
    this.overrideSaveFunction = function() {
        // 保存原始的 svgCanvas.save 函数
        const originalSave = svgCanvas.save;
        
        // 替换 svgCanvas.save 函数
        svgCanvas.save = () => {
            if (this.isAnkiEnv) {
                this.saveImage();
            } else if (originalSave) {
                originalSave.call(svgCanvas);
            }
        };
        
        this.log("Save function overridden for Anki integration");
    };
    
    /**
     * 重写导出功能
     */
    this.overrideExportFunction = function() {
        // 保存原始的 exportHandler
        const originalExportHandler = editor.exportHandler;
        
        // 创建新的 exportHandler
        const ankiExportHandler = (window, data) => {
            this.log("Export handler called with data:", data);
            if (this.isAnkiEnv) {
                this.exportToPNG(data);
            } else if (originalExportHandler) {
                originalExportHandler.call(editor, window, data);
            }
        };
        
        // 替换 editor.exportHandler
        editor.exportHandler = ankiExportHandler;
        
        // 重新绑定事件（关键！）
        svgCanvas.bind("exported", ankiExportHandler);
        
        this.log("Export function overridden for Anki integration");
    };
    
    /**
     * 导出为 PNG 并保存到 Anki
     */
    this.exportToPNG = function(data) {
        this.log("exportToPNG called");
        const issues = data.issues;
        
        // 显示任何问题
        if (issues && issues.length > 0) {
            this.log("Export issues:", issues);
        }
        
        // 创建隐藏的 canvas
        if (!$('#export_canvas').length) {
            $('<canvas>', {id: 'export_canvas'}).hide().appendTo('body');
        }
        const c = $('#export_canvas')[0];
        
        c.width = svgCanvas.contentW;
        c.height = svgCanvas.contentH;
        
        this.log(`Canvas size: ${c.width}x${c.height}`);
        
        // 检查 canvg 是否可用
        if (typeof window.canvg === 'undefined' && typeof canvg === 'undefined') {
            this.log("Error: canvg is not defined!");
            alert("无法导出 PNG：canvg 库未加载");
            return;
        }
        
        // 使用全局 canvg 函数
        const canvgFn = window.canvg || canvg;
        
        try {
            // 使用 canvg 渲染 SVG 到 canvas
            canvgFn(c, data.svg, {
                renderCallback: () => {
                    this.log("canvg render complete");
                    
                    // 获取 PNG data URI
                    // 为了减小文件大小，如果图像很大，我们可以适当缩小
                    let datauri;
                    const maxSize = 1200; // 最大边长
                    
                    if (c.width > maxSize || c.height > maxSize) {
                        // 需要缩小
                        const scale = Math.min(maxSize / c.width, maxSize / c.height);
                        const newWidth = Math.floor(c.width * scale);
                        const newHeight = Math.floor(c.height * scale);
                        
                        const tempCanvas = document.createElement('canvas');
                        tempCanvas.width = newWidth;
                        tempCanvas.height = newHeight;
                        const tempCtx = tempCanvas.getContext('2d');
                        
                        // 使用高质量缩放
                        tempCtx.imageSmoothingEnabled = true;
                        tempCtx.imageSmoothingQuality = 'high';
                        
                        // 绘制缩小的图像
                        tempCtx.drawImage(c, 0, 0, c.width, c.height, 0, 0, newWidth, newHeight);
                        
                        datauri = tempCanvas.toDataURL('image/png');
                        this.log(`Image resized from ${c.width}x${c.height} to ${newWidth}x${newHeight}`);
                    } else {
                        // 不需要缩小
                        datauri = c.toDataURL('image/png');
                    }
                    
                    if (!datauri) {
                        this.log("Failed to create data URI");
                        alert("无法创建图像数据");
                        return;
                    }
                    
                    this.log("PNG data URI created, length:", datauri ? datauri.length : 0);
                    
                    // 发送到 Anki
                    // 注意：data URI 可能很大，我们需要确保能传输
                    pycmd("png_save:" + datauri);
                    
                    this.log("PNG data sent to Anki");
                }
            });
        } catch (e) {
            this.log("Error in canvg:", e);
            alert("导出 PNG 时出错：" + e.message);
        }
    };
    
    /**
     * 日志输出（仅在 Anki 环境中）
     */
    this.log = function(message) {
        if (this.isAnkiEnv) {
            console.log("[AnkiIntegration] " + message);
        }
    };
};

// 创建实例但不立即初始化，等待 start.js 调用
window.MD = window.MD || {};