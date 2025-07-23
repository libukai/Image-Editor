/**
 * AnkiIntegration.js
 * Anki 插件集成模块 - 处理 Method Draw 与 Anki 的通信
 */

MD.AnkiIntegration = function() {
    const self = this;
    const MAX_IMAGE_SIZE = 1200; // PNG 导出最大边长
    
    // 状态管理
    this.isAnkiEnv = false;
    
    /**
     * 初始化 Anki 集成
     */
    this.init = function() {
        if (typeof pycmd === "function") {
            this.isAnkiEnv = true;
            this.setupBindings();
        } else {
            // 延迟检测 pycmd
            this.waitForPycmd(() => {
                this.isAnkiEnv = true;
                this.setupBindings();
            });
        }
    };
    
    /**
     * 等待 pycmd 可用
     */
    this.waitForPycmd = function(callback, maxAttempts = 30) {
        let attempts = 0;
        const check = () => {
            if (typeof pycmd === "function") {
                callback();
            } else if (attempts++ < maxAttempts) {
                setTimeout(check, 100);
            }
        };
        check();
    };
    
    /**
     * 设置所有绑定
     */
    this.setupBindings = function() {
        // 清空画布
        this.clearCanvas();
        
        // 请求初始图像
        pycmd("img_src");
        
        // 重写功能
        this.overrideSave();
        this.overrideExport();
        
        // 全局函数
        window.ankiAddonSetImg = this.setImage.bind(this);
        window.ankiAddonSaveImg = this.saveImage.bind(this);
    };
    
    /**
     * 清空画布
     */
    this.clearCanvas = function() {
        if (svgCanvas && svgCanvas.clear) {
            svgCanvas.clear();
            this.log("Canvas cleared");
        }
    };
    
    /**
     * 设置图像
     */
    this.setImage = function(data, type) {
        this.clearCanvas();
        
        if (type === "svg") {
            svgCanvas.setSvgString(data);
        } else {
            this.setRasterImage(data);
        }
    };
    
    /**
     * 设置栅格图像
     */
    this.setRasterImage = function(data) {
        const img = new Image();
        img.onload = () => this.createImageElement(img.width, img.height, data);
        img.onerror = () => this.createImageElement(100, 100, data); // 默认尺寸
        img.src = data;
    };
    
    /**
     * 创建图像元素
     */
    this.createImageElement = function(width, height, data) {
        // 设置画布
        svgCanvas.setResolution(width, height);
        $("#canvas_width").val(width);
        $("#canvas_height").val(height);
        
        // 创建图像
        const image = svgCanvas.addSvgElementFromJson({
            element: "image",
            attr: {
                x: 0,
                y: 0,
                width: width,
                height: height,
                id: svgCanvas.getNextId(),
                style: "pointer-events:inherit"
            }
        });
        
        svgCanvas.setHref(image, data);
        
        // 居中
        svgCanvas.selectOnly([image]);
        svgCanvas.alignSelectedElements("m", "page");
        svgCanvas.alignSelectedElements("c", "page");
        svgCanvas.clearSelection();
        
        editor.canvas.update();
    };
    
    /**
     * 保存图像
     */
    this.saveImage = function() {
        svgCanvas.clearSelection();
        pycmd("svg_save:" + svgCanvas.getSvgString());
    };
    
    /**
     * 重写保存功能
     */
    this.overrideSave = function() {
        const originalSave = svgCanvas.save;
        svgCanvas.save = () => {
            if (this.isAnkiEnv) {
                this.saveImage();
            } else {
                originalSave.call(svgCanvas);
            }
        };
    };
    
    /**
     * 重写导出功能
     */
    this.overrideExport = function() {
        const ankiExportHandler = (window, data) => {
            if (this.isAnkiEnv) {
                this.exportToPNG(data);
            } else if (editor.exportHandler) {
                editor.exportHandler.call(editor, window, data);
            }
        };
        
        editor.exportHandler = ankiExportHandler;
        svgCanvas.bind("exported", ankiExportHandler);
    };
    
    /**
     * 导出为 PNG
     */
    this.exportToPNG = function(data) {
        // 获取或创建 canvas
        let canvas = document.getElementById('export_canvas');
        if (!canvas) {
            canvas = document.createElement('canvas');
            canvas.id = 'export_canvas';
            canvas.style.display = 'none';
            document.body.appendChild(canvas);
        }
        
        canvas.width = svgCanvas.contentW;
        canvas.height = svgCanvas.contentH;
        
        // 检查 canvg
        const canvgFn = window.canvg || canvg;
        if (!canvgFn) {
            alert("无法导出 PNG：canvg 库未加载");
            return;
        }
        
        try {
            canvgFn(canvas, data.svg, {
                renderCallback: () => this.processPNG(canvas)
            });
        } catch (e) {
            alert("导出 PNG 时出错：" + e.message);
        }
    };
    
    /**
     * 处理 PNG 数据
     */
    this.processPNG = function(canvas) {
        let datauri;
        
        // 检查是否需要缩放
        if (canvas.width > MAX_IMAGE_SIZE || canvas.height > MAX_IMAGE_SIZE) {
            datauri = this.resizeCanvas(canvas);
        } else {
            datauri = canvas.toDataURL('image/png');
        }
        
        if (datauri) {
            pycmd("png_save:" + datauri);
            this.log("PNG exported, size: " + datauri.length);
        } else {
            alert("无法创建 PNG 数据");
        }
    };
    
    /**
     * 缩放画布
     */
    this.resizeCanvas = function(sourceCanvas) {
        const scale = Math.min(MAX_IMAGE_SIZE / sourceCanvas.width, MAX_IMAGE_SIZE / sourceCanvas.height);
        const newWidth = Math.floor(sourceCanvas.width * scale);
        const newHeight = Math.floor(sourceCanvas.height * scale);
        
        const tempCanvas = document.createElement('canvas');
        tempCanvas.width = newWidth;
        tempCanvas.height = newHeight;
        
        const ctx = tempCanvas.getContext('2d');
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'high';
        ctx.drawImage(sourceCanvas, 0, 0, newWidth, newHeight);
        
        this.log(`Image resized: ${sourceCanvas.width}x${sourceCanvas.height} → ${newWidth}x${newHeight}`);
        return tempCanvas.toDataURL('image/png');
    };
    
    /**
     * 日志输出
     */
    this.log = function(message) {
        if (this.isAnkiEnv) {
            console.log("[AnkiIntegration] " + message);
        }
    };
};

window.MD = window.MD || {};