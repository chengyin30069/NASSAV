package main

import (
	"encoding/json"
	"encoding/xml"
	"fmt"
	"io"
	"io/ioutil"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

// 服务器配置
const (
	basePath   = "/vol2/1000/MissAV"
	serverPort = ":8080"
)

// 全局缓存
var (
	videoListCache []VideoItem
	cacheMutex     sync.RWMutex
	logger         = log.New(os.Stdout, "[MissAV] ", log.LstdFlags|log.Lshortfile)
)

// VideoItem 表示视频列表项
type VideoItem struct {
	ID     string `json:"id"`
	Title  string `json:"title"`
	Poster string `json:"poster"`
}

// VideoDetail 视频详细信息
type VideoDetail struct {
	ID          string   `json:"id"`
	Title       string   `json:"title"`
	ReleaseDate string   `json:"releaseDate"`
	Fanarts     []string `json:"fanarts"`
	VideoFile   string   `json:"videoFile,omitempty"`
}

// NfoFile NFO文件结构
type NfoFile struct {
	XMLName     xml.Name `xml:"movie"`
	Title       string   `xml:"title"`
	ReleaseDate string   `xml:"releasedate"`
	Premiered   string   `xml:"premiered"`
}

func enableCORS(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// 允许的域名（生产环境应替换为实际前端域名）
		w.Header().Set("Access-Control-Allow-Origin", "*")

		// 允许的HTTP方法
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")

		// 允许的请求头
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")

		// 允许携带Cookie（如果需要）
		w.Header().Set("Access-Control-Allow-Credentials", "true")

		// 预检请求直接返回200
		if r.Method == "OPTIONS" {
			w.WriteHeader(http.StatusOK)
			return
		}

		next.ServeHTTP(w, r)
	})
}

func main() {
	logger.Println("Starting MissAV server...")

	// 初始化缓存
	if err := buildVideoListCache(); err != nil {
		logger.Fatalf("Failed to build initial cache: %v", err)
	}

	// 启动定时缓存更新
	go startCacheUpdater(30 * time.Minute)

	// 设置路由
	mux := http.NewServeMux()
	mux.HandleFunc("/api/videos", listVideosHandler)
	mux.HandleFunc("/api/videos/", videoDetailHandler)
	mux.HandleFunc("/file/", imageHandler)

	// 包装CORS中间件
	handler := enableCORS(mux)

	logger.Printf("Server started on port %s", serverPort)
	log.Fatal(http.ListenAndServe("0.0.0.0"+serverPort, handler))
}

// startCacheUpdater 定时更新缓存
func startCacheUpdater(interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for range ticker.C {
		logger.Println("Starting scheduled cache update...")
		if err := buildVideoListCache(); err != nil {
			logger.Printf("Cache update failed: %v", err)
		} else {
			logger.Println("Cache updated successfully")
		}
	}
}

// buildVideoListCache 构建视频列表缓存
func buildVideoListCache() error {
	cacheMutex.Lock()
	defer cacheMutex.Unlock()

	startTime := time.Now()
	logger.Println("Building video list cache...")

	// 清空现有缓存
	videoListCache = nil

	// 读取目录
	files, err := os.ReadDir(basePath)
	if err != nil {
		logger.Printf("Error reading directory %s: %v", basePath, err)
		return fmt.Errorf("read directory failed: %w", err)
	}

	var count int
	for _, file := range files {
		if !file.IsDir() {
			continue
		}

		videoID := file.Name()
		posterPath := filepath.Join(basePath, videoID, videoID+"-poster.jpg")

		if _, err := os.Stat(posterPath); err != nil {
			logger.Printf("Poster not found for %s: %v", videoID, err)
			continue
		}

		title, _, err := parseTitleAndDate(videoID)
		if err != nil {
			logger.Printf("Failed to parse NFO for %s: %v", videoID, err)
			title = videoID
		}

		videoListCache = append(videoListCache, VideoItem{
			ID:     videoID,
			Title:  title,
			Poster: fmt.Sprintf("/file/%s/%s-poster.jpg", videoID, videoID),
		})
		count++
	}

	logger.Printf("Cache built successfully. Items: %d, Duration: %v",
		count, time.Since(startTime))
	return nil
}

// parseTitleAndDate 解析NFO文件获取标题和日期
func parseTitleAndDate(videoID string) (title, releaseDate string, err error) {
	nfoPath := filepath.Join(basePath, videoID, videoID+".nfo")

	// 使用os.Open确保能处理BOM头
	file, err := os.Open(nfoPath)
	if err != nil {
		return "", "", fmt.Errorf("open file failed: %w", err)
	}
	defer file.Close()

	// 创建UTF-8解码器（自动处理BOM头）
	decoder := xml.NewDecoder(file)
	decoder.CharsetReader = func(charset string, input io.Reader) (io.Reader, error) {
		// 强制使用UTF-8，忽略文件声明的编码
		return input, nil
	}

	var nfo NfoFile
	if err := decoder.Decode(&nfo); err != nil {
		return "", "", fmt.Errorf("xml decode failed: %w", err)
	}

	// 确定发布日期
	date := nfo.ReleaseDate
	if date == "" {
		date = nfo.Premiered
	}

	// 确保标题不为空
	if nfo.Title == "" {
		nfo.Title = videoID
	}

	return nfo.Title, date, nil
}

// listVideosHandler 获取视频列表
func listVideosHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		httpError(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	cacheMutex.RLock()
	defer cacheMutex.RUnlock()

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	if err := json.NewEncoder(w).Encode(videoListCache); err != nil {
		logger.Printf("Error encoding video list: %v", err)
		httpError(w, "Internal server error", http.StatusInternalServerError)
	}
}

// videoDetailHandler 获取视频详情
func videoDetailHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		httpError(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	videoID := strings.TrimPrefix(r.URL.Path, "/api/videos/")
	if videoID == "" {
		httpError(w, "Invalid video ID", http.StatusBadRequest)
		return
	}

	detail := VideoDetail{ID: videoID}
	startTime := time.Now()

	// 解析NFO文件
	title, date, err := parseTitleAndDate(videoID)
	if err != nil {
		logger.Printf("NFO parse for %s failed: %v", videoID, err)
		detail.Title = videoID
		detail.ReleaseDate = "Unknown"
	} else {
		detail.Title = title
		detail.ReleaseDate = date
	}

	// 查找fanart图片
	fanartDir := filepath.Join(basePath, videoID)
	if files, err := ioutil.ReadDir(fanartDir); err == nil {
		for _, file := range files {
			name := file.Name()
			if !file.IsDir() && strings.HasPrefix(name, videoID+"-fanart") &&
				strings.HasSuffix(name, ".jpg") {
				detail.Fanarts = append(detail.Fanarts,
					fmt.Sprintf("/file/%s/%s", videoID, name))
			}
		}
	} else {
		logger.Printf("Error reading fanart dir for %s: %v", videoID, err)
	}

	// 检查视频文件
	videoFile := filepath.Join(basePath, videoID, videoID+".mp4")
	if _, err := os.Stat(videoFile); err == nil {
		detail.VideoFile = fmt.Sprintf("/file/%s/%s.mp4", videoID, videoID)
	}

	logger.Printf("Processed detail request for %s in %v", videoID, time.Since(startTime))

	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	if err := json.NewEncoder(w).Encode(detail); err != nil {
		logger.Printf("Error encoding detail for %s: %v", videoID, err)
		httpError(w, "Internal server error", http.StatusInternalServerError)
	}
}

// imageHandler 处理图片请求
func imageHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		httpError(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	pathParts := strings.Split(strings.TrimPrefix(r.URL.Path, "/file/"), "/")
	if len(pathParts) < 2 {
		httpError(w, "Invalid image path", http.StatusBadRequest)
		return
	}

	videoID := pathParts[0]
	filename := strings.Join(pathParts[1:], "/")
	imagePath := filepath.Join(basePath, videoID, filename)

	// 安全检查
	if !strings.HasPrefix(filepath.Clean(imagePath), filepath.Clean(basePath)) {
		httpError(w, "Invalid path", http.StatusBadRequest)
		return
	}

	fileInfo, err := os.Stat(imagePath)
	if os.IsNotExist(err) {
		http.NotFound(w, r)
		return
	} else if err != nil {
		logger.Printf("Error accessing file %s: %v", imagePath, err)
		httpError(w, "Internal server error", http.StatusInternalServerError)
		return
	}

	// 设置Content-Type
	switch filepath.Ext(filename) {
	case ".jpg", ".jpeg":
		w.Header().Set("Content-Type", "image/jpeg")
	case ".png":
		w.Header().Set("Content-Type", "image/png")
	case ".mp4":
		w.Header().Set("Content-Type", "video/mp4")
	}

	logger.Printf("Serving file %s (Size: %d)", imagePath, fileInfo.Size())
	http.ServeFile(w, r, imagePath)
}

// httpError 统一的HTTP错误响应
func httpError(w http.ResponseWriter, message string, code int) {
	logger.Printf("HTTP Error %d: %s", code, message)
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(map[string]string{"error": message})
}
