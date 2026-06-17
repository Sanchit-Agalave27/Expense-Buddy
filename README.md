# 💰 Expense Buddy

[![Live Demo](https://img.shields.io/badge/Live_Demo-View_Project-blue?style=for-the-badge)](https://expense-buddy-l34y.onrender.com)
[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
[![TailwindCSS](https://img.shields.io/badge/Tailwind_CSS-38B2AC?style=for-the-badge&logo=tailwind-css&logoColor=white)](https://tailwindcss.com/)

**Expense Buddy** is a modern, fast, and secure personal finance tracking application built with FastAPI. It empowers users to take control of their finances by providing visibility into their spending habits, setting monthly budgets, and achieving financial goals.

---

## ✨ Features

* **Secure Authentication:** User registration and login using industry-standard JWT (JSON Web Tokens) and bcrypt password hashing.
* **Financial Dashboard:** A comprehensive overview of your Monthly Income, Target Budget, Total Spent, and Net Balance.
* **Transaction Management:** Easily log, edit, and delete daily expenses with specific categories (Food, Travel, Housing, etc.).
* **Data Visualization:** Interactive Bar and Doughnut charts built with Chart.js to visually analyze where your money is going.
* **Data Export:** One-click CSV report generation to download your transaction history for external use.
* **Modern UI:** A clean, responsive, light-themed interface built seamlessly with Tailwind CSS.

---

## 🛠️ Tech Stack

**Backend:**
* [FastAPI](https://fastapi.tiangolo.com/) - High-performance web framework
* [SQLAlchemy](https://www.sqlalchemy.org/) - Database ORM
* [SQLite](https://www.sqlite.org/) - Lightweight, file-based database
* [PyJWT](https://pyjwt.readthedocs.io/en/stable/) & [bcrypt](https://pypi.org/project/bcrypt/) - Security and authentication

**Frontend:**
* [Jinja2](https://jinja.palletsprojects.com/) - Server-side HTML templating
* [Tailwind CSS](https://tailwindcss.com/) - Utility-first CSS styling (via CDN)
* [Chart.js](https://www.chartjs.org/) - JavaScript charting library (via CDN)

---

## 📂 Project Structure

```text
ExpenseBuddy/
├── main.py                 # Core FastAPI backend, routing, and database logic
├── requirements.txt        # Python package dependencies
├── finance_app_final.db    # SQLite database (auto-generated)
├── Frontend/               # Jinja2 HTML templates
│   ├── index.html          # Main Dashboard
│   ├── analytics.html      # Chart visualizations
│   ├── update.html         # Edit transaction form
│   ├── login.html          # User authentication
│   └── signup.html         # User registration
└── static/                 # Directory for static assets (optional)