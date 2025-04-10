package main

import (
	"database/sql"
	"fmt"
	"io"
	"log"
	"net/http"
	"os/exec"
	"strings"

	_ "github.com/mattn/go-sqlite3"
)

// 预定义的API密钥
const apiKey = "IBHUSDBWQHJEJOBDSW"

func main() {
	// 设置路由和处理函数
	http.HandleFunc("/process", authMiddleware(processHandler))

	// 启动服务器
	fmt.Println("Server starting on port 49530...")
	log.Fatal(http.ListenAndServe(":49530", nil))
}

// 鉴权中间件
func authMiddleware(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		// 检查请求方法是否为POST
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		// 从请求头获取API密钥
		authHeader := r.Header.Get("Authorization")
		if authHeader == "" {
			http.Error(w, "Authorization header missing", http.StatusUnauthorized)
			return
		}

		// 验证API密钥
		if !strings.HasPrefix(authHeader, "Bearer ") {
			http.Error(w, "Invalid authorization format", http.StatusUnauthorized)
			return
		}

		token := strings.TrimPrefix(authHeader, "Bearer ")
		if token != apiKey {
			http.Error(w, "Invalid API key", http.StatusUnauthorized)
			return
		}

		// 如果验证通过，调用下一个处理函数
		next(w, r)
	}
}

// 处理POST请求的函数
func processHandler(w http.ResponseWriter, r *http.Request) {
	// 读取请求体
	bodyBytes, err := io.ReadAll(r.Body)
	if err != nil {
		http.Error(w, "Failed to read request body", http.StatusBadRequest)
		return
	}
	defer r.Body.Close()

	// 将请求体转换为字符串，强制大写
	id := strings.ToUpper(string(bodyBytes))
	if id == "" {
		http.Error(w, "ID is required", http.StatusBadRequest)
		return
	}
	fmt.Printf("Received ID: %s\n", id)

	// 检查sqlite里面是否有这个车牌号
	db, err := sql.Open("sqlite3", "../db/downloaded.db")
	if err != nil {
		log.Fatal(err)
	}
	defer db.Close()

	exists, err := checkStringExists(db, id)
	if err != nil {
		log.Fatal(err)
	}

	response := fmt.Sprintf("%s already downloaded", id)
	// 执行Python脚本
	if !exists {
		response = fmt.Sprintf("Add %s to download queue", id)
		go func() {
			cmd := exec.Command("sh", "-c", fmt.Sprintf("cd .. && python3 main.py %s", id))
			err := cmd.Run()
			if err != nil {
				log.Printf("command exec failed: %v", err)
			} else {
				log.Println("command exec succ!")
			}
		}()
	}
	fmt.Println(response)

	// 设置响应内容类型
	w.Header().Set("Content-Type", "text/plain")
	w.Write([]byte(response))
}

func checkStringExists(db *sql.DB, target string) (bool, error) {
	var exists bool
	query := "SELECT EXISTS(SELECT 1 FROM MissAV WHERE bvid = ? LIMIT 1)"
	err := db.QueryRow(query, target).Scan(&exists)
	return exists, err
}
