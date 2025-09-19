# PostgreSQL WebUI Simple
* # [github](https://github.com/jjajjara/pgsql-webui-simple)
* # [hub.docker.com](https://hub.docker.com/r/jjajjara/pgsql-webui-simple)
![ex_screenshot](https://github.com/user-attachments/assets/7e82a4d7-abb0-4746-acf7-2e355972f634)

A simple, lightweight, and configuration-based web UI for performing CRUD (Create, Read, Update, Delete) operations on specified PostgreSQL tables. This tool is designed to run in a Docker container without any code modifications, making it ideal for air-gapped environments or quick database management tasks.

## Features

* **Configuration via Environment Variables**: No need to rebuild or change code. Just set your database connection and target tables in the `.env` file.
* **Full CRUD Functionality**: An intuitive interface for viewing, creating, updating, and deleting records.
* **Single Docker Container**: Runs as a self-contained Docker image, perfect for easy deployment.
* **No External Dependencies**: Designed for air-gapped environments. It runs without any external network access after the initial Docker image is pulled.
* **Modern Dark UI**: A clean and modern user interface for managing your data.

## Quick Start with Docker Compose

Follow these steps to get the application running in minutes.

### Prerequisites

* [Docker](https://docs.docker.com/get-docker/)
* [Docker Compose](https://docs.docker.com/compose/install/)

### 1. Create Project Files

First, create a directory for your project and add the following two files.

`docker-compose.yml`:
```yaml
services:
  pgsql-webui-simple:
    image: jjajjara/pgsql-webui-simple:latest
    container_name: pgsql-webui-simple
    restart: unless-stopped
    ports:
      - "3000:8000"
    env_file:
      - .env
```

`.env`:
```ini
# .env file content

# 1. DATABASE_URL
# Format: postgresql://[USERNAME]:[PASSWORD]@[DB_HOST]:[PORT]/[DB_NAME]
DATABASE_URL=postgresql://db_username:db_password@db_server:db_port/db_name

# 2. TABLES
# A comma-separated list of table names you want to manage.
TABLES=sample_data,test_db
```

### 2. Configure Your Database

Open the `.env` file and replace the placeholder values with your actual PostgreSQL database credentials and the list of tables you wish to manage.

**Important:** If your database is running on the same machine (your local PC), use `host.docker.internal` instead of `localhost` or `127.0.0.1` for the `DB_HOST`. For example: `postgresql://user:pass@host.docker.internal:5432/mydb`.

### 3. Run the Application

Navigate to your project directory in the terminal and run the following command:

```bash
docker-compose up -d
```

The `-d` flag runs the container in detached mode (in the background).

### 4. Access the Web UI

Once the container is running, open your web browser and go to:

**`http://localhost:3000`**

You should now see the web interface, ready to manage the tables you specified.

## Stopping the Application

To stop the container, run the following command in the same directory:

```bash
docker-compose down
```
