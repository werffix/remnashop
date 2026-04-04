<div align="center" markdown>

<p align="center">
    <u><b>ENGLISH</b></u> •
    <a href="https://github.com/snoups/remnashop/blob/main/README.ru_RU.md"><b>РУССКИЙ</b></a>
</p>

![remnashop](https://github.com/user-attachments/assets/57ba5832-4646-45e1-b082-f8f2f5e82c3e)

**This project is a Telegram bot for selling VPN subscriptions, integrated with Remnawave.**

[![Static Badge](https://img.shields.io/badge/public_group-white?style=social&logo=Telegram&logoColor=blue&logoSize=auto&labelColor=white&link=https%3A%2F%2Ft.me%2Fsn0ups)](https://t.me/remna_shop)
[![Static Badge](https://img.shields.io/badge/remnawave-white?style=social&logo=Telegram&logoColor=blue&logoSize=auto&labelColor=white&link=https%3A%2F%2Ft.me%2Fsnoups)](https://t.me/+xQs17zMzwCY1NzYy)
![GitHub Repo stars](https://img.shields.io/github/stars/snoups/remnashop)

<p align="center">
    <br />
    <p align="center">
        <a href="https://remnashop.mintlify.app/docs/en/overview/releases">
            <img src="https://img.shields.io/badge/Get%20Started-%E2%86%92-0969da?style=for-the-badge&labelColor=0969da&color=0969da" alt="Get Started" width="200" height="auto">
        </a>
    </p>
    <a href="https://github.com/snoups/remnashop/releases">
        <img src="https://img.shields.io/github/v/release/snoups/remnashop?label=Latest%20release&style=social" alt="Latest release">



🚀 Обновление RemnaShop


⸻


📥 Клонирование репозитория

cd
rm -rf remnashop
git clone https://github.com/werffix/remnashop
cd remnashop


⸻

🐳 Сборка и публикация Docker-образа

docker build -t ghcr.io/werffix/remnashop:latest .

echo <GITHUB_TOKEN> | docker login ghcr.io -u werffix --password-stdin

docker push ghcr.io/werffix/remnashop:latest


⸻

🔄 Обновление и запуск сервиса

cd /opt/remnashop && docker-compose pull && docker-compose down && RESET_ASSETS=true docker-compose up -d && docker-compose logs -f


⸻

⚠️ Важно после обновления

После запуска бота необходимо перезапустить nginx-контейнер:

cd /opt/remnawave/nginx

sudo docker stop -t 0 remnawave-nginx

Затем запустить контейнер remnawave-nginx снова (обычно через docker-compose up -d или ваш способ запуска).

💡 После этого бот запустится автоматически.

⸻

📌 Примечания
	•	Замените <GITHUB_TOKEN> на ваш реальный токен GitHub.
	•	Убедитесь, что у вас есть доступ к ghcr.io.
	•	Все команды предполагают наличие docker и docker-compose.

⸻


    </a>
</p>
</div>
