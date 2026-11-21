// notifications: avisos por correo de juguete (Go + Gin).
package main

import "github.com/gin-gonic/gin"

func main() {
	r := gin.Default()
	r.GET("/health", func(c *gin.Context) { c.JSON(200, gin.H{"ok": true}) })
	r.POST("/notify", func(c *gin.Context) {
		db.Create(&Notification{To: c.PostForm("to")})
		c.JSON(202, gin.H{"queued": true})
	})
	r.Run(":8080")
}
