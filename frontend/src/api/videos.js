import axios from 'axios'

const API_BASE = 'http://192.168.31.61:31471'

export default {
    async getVideoList() {
        const response = await axios.get(`${API_BASE}/api/videos`)
        return response.data.map(video => ({
            ...video,
            poster: `${API_BASE}${video.poster}` // 拼接完整URL
        }))
    },

    async getVideoDetail(id) {
        const response = await axios.get(`${API_BASE}/api/videos/${id}`)
        const data = response.data

        // 处理详情数据中的路径
        return {
            ...data,
            poster: `${API_BASE}${data.fanarts[0]}`,
            videoFile: data.videoFile ? `${API_BASE}${data.videoFile}` : null,
            fanarts: data.fanarts?.map(img => `${API_BASE}${img}`) || []
        }
    }
}