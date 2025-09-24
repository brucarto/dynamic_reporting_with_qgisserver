# Dynamic Reporting with QGIS Server

This demo, created for **FOSS4G Belgium 2025**, demonstrates how **QGIS Server** can be used to generate dynamic PDF files. QGIS Server allows you to prepare a dynamic map using the **QGIS Desktop Layout Manager**. Using **ReportLab**, a PDF file is created within a **Django** environment.

---

## Requirements
- A Linux system or **Windows Subsystem for Linux (WSL)**
- **QGIS** (version **3.40** or later)
- **Docker** or **Podman**

---

## Preparing a QGIS Project

Use **QGIS version 3.40 or later** to complete this demo, as some functionalities described here are not available in earlier versions.

The project file **`collecto.qgz`** is included in this repository. It is configured with public data, allowing free testing. The file contains the locations of **Collecto stops in the Brussels Capital Region**.  
If you use your own data sources, ensure they are accessible to QGIS Server.

The project includes:
- A group of layers for a **detailed view**
- A group of layers for an **overview**

**Scale settings:**
- Minimum scale for detailed layers: **1:10,000**
- Maximum scale for overview layers: **1:10,000**

Layers controlled by the atlas must be **vector layers**.

A layout is created with a **custom page size**. An **atlas** is generated using the Collecto layer as the dynamic data source.

---

## Installing QGIS Server

Ensure **Docker** or **Podman** is installed on your Linux server.

### Create a QGIS data folder:
```bash
mkdir -p /srv/qgis/data
```

### Install QGIS Server:
```bash
podman run -d --name qgis-server \
  -p 5555:80 \
  -v /srv/qgis/data:/data:Z \
  -e QGIS_SERVER_LOG_LEVEL=2 \
  -e QGIS_SERVER_LOG_STDERR=2 \
  camptocamp/qgis-server:3.40
```

> **Note:**  
> - Ensure the installed version matches your **QGIS Desktop** version.  
> - The image from **Camptocamp** is used because the default Docker images do not include QGIS Server 3.

### Download the project file:
```bash
cd /srv/qgis/data
wget https://github.com/brucarto/dynamic_reporting_with_qgisserver/raw/4817c4f096a7f9c89b2235dd20b9afa4ad45f3e7/collecto.qgz
```

You can now create the template using the following WMS request:

```
http://localhost:5555/?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetPrint&MAP=/data/collecto.qgz&TEMPLATE=stoplayout&FORMAT=png&CRS=EPSG:3812&DPI=50&ATLAS_PK=2
```

> ⚠️ Important Notes:
> - **Do not use the `LAYERS` parameter** in your request. This parameter will filter the available layers in your render.
> - If the **overview map is not printed**, there may be an issue with the map extents. You can manually adjust the extents using the `map0:EXTENT` parameter:
> 
> ```
> ...&map0:EXTENT=140750,161250,158250,178500
> ```

---
## Create a Django Environment (Optional)

That was easy! Let's create a small Django project now.

### Creating Folders

First, create a data folder for the Django project:
```bash
mkdir -p /srv/django_data
chown -R $USER:$USER /srv/django_data
```

Create a folder for the Docker files:
```bash
mkdir -p /srv/docker/django
cd /srv/docker/django
```

### Creating requirements.txt

Create a new file named **`requirements.txt`** who will contain the Python libraries to install:

```requirements.txt
Django>=4.2,<5.0
reportlab>=4.0.0
requests>=2.31.0
```

### Creating Dockerfiles

The Docker container file will specify the tools to be installed.  
Create a new file named **`django_container`** and add the following content:

```dockerfile
# Use a small Python base image
FROM python:3.12-slim

# Install build prerequisites for common DB drivers
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev gettext \
 && rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN useradd -m appuser
WORKDIR /app

# Install Python dependencies globally in the image
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r /tmp/requirements.txt

# Switch to unprivileged user by default
USER appuser
```

### Initialize Django

Now you can build the Docker image:

```bash
podman build -t report-django:latest -f django_container .
```

### Initialize the Django Project

Run the following command to create a new Django project inside the mounted volume:

```bash
podman run --rm -it \
  -v /srv/django_data:/app:Z,U \
  -w /app \
  report-django django-admin startproject reportweb .
```

### Create a New App

Create a new app named **`report`** to handle PDF creation:

```bash
podman run --rm -it \
  -v /srv/django_data:/app:Z,U \
  -w /app \
  report-django python manage.py startapp report
```

### Update Project Settings

Edit the file **`/srv/django_data/reportweb/settings.py`** and update the following:

```python
ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    ...
    'report',
]
```

> **Note:**  
> - Since this is an internal server, you can allow all hosts (`'*'`).  
> - For a production environment, you must define a specific list of allowed hosts for security reasons.

### Update Project URLs

Edit the file **`/srv/django_data/reportweb/urls.py`**:

```python
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('report/', include('report.urls')),
]
```

---

## Creating a PDF File

You now have a framework to handle your requests. Next, we will add a **ReportLab** script to the project to generate a PDF file. Reportlab is a Python library for generating PDF-files.

### Add the ReportLab Script

Run the following commands to download the script, generated by AI:

```bash
cd /srv/django_data/report/
wget https://raw.githubusercontent.com/brucarto/dynamic_reporting_with_qgisserver/refs/heads/main/collecto.py
```

### Update App URLs

Edit the file **`/srv/django_data/report/urls.py`**:

```python
from django.urls import path
from . import views, collecto

urlpatterns = [
    path('collecto/<str:stop>/', collecto.info),
]
```

### Run the Django Server

Start the Django development server inside the container:

```bash
podman run --rm -it \
  -v /srv/django_data:/app:Z,U \
  -w /app \
  -p 8000:8000 \
  report-django python manage.py runserver 0.0.0.0:8000
```

### Test the Request

Open your browser and navigate to:

```
http://localhost:8000/report/collecto/2/
```

Your browser will display a **PDF output** generated dynamically.

---

## Next Steps

You can connect your Django framework with **Apache** or **NGINX** to create a fully functional web application.

---

## Contact

For any questions or inquiries, please contact us at **mobigis@sprb.brussels**.
