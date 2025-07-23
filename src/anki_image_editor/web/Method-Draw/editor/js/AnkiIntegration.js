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
        // 请求初始图像
        pycmd("img_src");
        
        // 重写保存功能
        this.overrideSaveFunction();
        
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
            // 设置画布尺寸
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