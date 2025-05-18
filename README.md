# BrightSide News - Installation and Deployment Guide

maxresdefault.jpg
![alt text](maxresdefault.jpg)

This guide provides instructions on how to set up and run the BrightSide News Flask application locally and offers considerations for deploying it to platforms like AWS or Azure.

## Prerequisites

*   **Python:** Version 3.11 or higher is recommended.
*   **pip:** Python's package installer, usually included with Python.
*   **Git:** (Optional) If cloning the repository directly.
*   **Virtual Environment Tool:** (Recommended) `venv` (built-in) or `virtualenv`.

## Local Setup

1.  **Get the Code:**
    *   If you received a zip file, extract it to your desired location.
    *   If using Git, clone the repository: `git clone <repository_url>`
    *   Navigate into the project directory (e.g., `cd brightside_news`).

2.  **Create and Activate Virtual Environment:**
    *   It is highly recommended to use a virtual environment to isolate dependencies.
    *   `python3 -m venv venv` (or `python -m venv venv`)
    *   Activate the environment:
        *   **Linux/macOS:** `source venv/bin/activate`
        *   **Windows (cmd):** `venv\Scripts\activate.bat`
        *   **Windows (PowerShell):** `venv\Scripts\Activate.ps1`
    *   You should see `(venv)` prefixed to your command prompt.

3.  **Install Dependencies:**
    *   Install all required Python packages using the `requirements.txt` file:
        `pip install -r requirements.txt`

4.  **Download NLTK Data:**
    *   The application uses the NLTK library for sentiment analysis, which requires the `vader_lexicon` dataset.
    *   Run the following command to download it:
        `python -m nltk.downloader vader_lexicon`
    *   This will download the data to the default NLTK data path (usually within your home directory).

5.  **Set Environment Variables (Optional but Recommended):**
    *   The admin panel uses default credentials (`admin`/`password`) if environment variables are not set. For security, it's better to set them:
        *   **Linux/macOS:**
            ```bash
            export ADMIN_USER="your_admin_username"
            export ADMIN_PASS="your_strong_password"
            ```
        *   **Windows (cmd):**
            ```cmd
            set ADMIN_USER="your_admin_username"
            set ADMIN_PASS="your_strong_password"
            ```
        *   **Windows (PowerShell):**
            ```powershell
            $env:ADMIN_USER="your_admin_username"
            $env:ADMIN_PASS="your_strong_password"
            ```
    *   Replace `your_admin_username` and `your_strong_password` accordingly.

6.  **Run the Application (Development Server):**
    *   Execute the main application file:
        `python src/main.py`
    *   The application will start fetching news (this might take a moment) and then run the development server, typically accessible at `http://127.0.0.1:5000` or `http://localhost:5000`.
    *   The admin panel is available at `/admin` (e.g., `http://127.0.0.1:5000/admin`).
    *   **Note:** The Flask development server is not suitable for production use.

## Deployment Considerations (AWS, Azure, etc.)

Deploying a Flask application involves several steps beyond the local setup. Here are general guidelines:

1.  **Production WSGI Server:**
    *   Do not use the built-in Flask development server (`app.run()`) in production.
    *   Use a production-ready WSGI server like **Gunicorn** (popular on Linux) or **Waitress** (cross-platform).
    *   **Example (Gunicorn):**
        *   Install Gunicorn: `pip install gunicorn`
        *   Add `gunicorn` to your `requirements.txt`.
        *   Run the app using Gunicorn (adjust workers as needed):
            `gunicorn --bind 0.0.0.0:5000 "src.main:app"` (Run from the project root directory)
    *   **Example (Waitress):**
        *   Install Waitress: `pip install waitress`
        *   Add `waitress` to your `requirements.txt`.
        *   Run the app using Waitress:
            `waitress-serve --host 0.0.0.0 --port=5000 src.main:app`

2.  **Platform Choice (AWS/Azure):**
    *   **AWS:** Options include EC2 (virtual machines), Elastic Beanstalk (PaaS), App Runner, or container services (ECS, EKS).
    *   **Azure:** Options include App Service (PaaS), Virtual Machines, Azure Kubernetes Service (AKS).
    *   PaaS options (Elastic Beanstalk, App Service) often simplify deployment by handling infrastructure, scaling, and updates.

3.  **Environment Variables:**
    *   Configure `ADMIN_USER` and `ADMIN_PASS` securely using the platform's environment variable management system (e.g., Elastic Beanstalk configuration, App Service Application Settings).
    *   **Never hardcode credentials in your source code.**

4.  **Database (Future Enhancement):**
    *   Currently, the application uses an in-memory cache. For persistence and scalability, consider integrating a database (e.g., PostgreSQL, MySQL, SQLite for simpler cases) and using a managed database service (AWS RDS, Azure Database).

5.  **Background Tasks (Future Enhancement):**
    *   The news fetching currently happens within the web request cycle or on startup. For better performance and reliability, move the `fetch_and_filter_feeds` task to a background job scheduler (e.g., Celery with Redis/RabbitMQ, APScheduler).

6.  **Static Files:**
    *   For better performance, configure your web server (like Nginx or Apache, if used as a reverse proxy) or use a CDN (Content Delivery Network) to serve static files (`style.css`) directly, rather than through Flask.

7.  **HTTPS:**
    *   Ensure your deployed application uses HTTPS for security. Most PaaS platforms and load balancers offer easy ways to configure SSL/TLS certificates.

This guide provides a starting point. Specific deployment steps will vary significantly based on your chosen cloud provider and service.

