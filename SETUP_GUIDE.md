# Fly Assessment Portal — Setup & Deployment Guide

This guide details the step-by-step process for deploying the **Fly Assessment Portal** using **MongoDB Atlas** for database storage, **HuggingFace Spaces** for the backend, and **GitHub Pages** for the static frontend.

---

## 1. MongoDB Atlas Setup (Database)

MongoDB Atlas is a fully managed cloud database service. We will use a free M0 cluster to host all data.

1. **Sign Up / Log In**:
   - Go to [MongoDB Atlas](https://www.mongodb.com/cloud/atlas/register) and create a free account.
2. **Create a Database Cluster**:
   - Click **Create** to deploy a new cluster.
   - Choose the **M0 Free Tier** (Shared RAM & storage).
   - Select your preferred Cloud Provider (e.g., AWS) and Region (e.g., N. Virginia or any close to you).
   - Click **Create Deployment**.
3. **Configure Database Security**:
   - **Database User**: Create a database user. Set a username (e.g., `fly_user`) and a secure password. Save these credentials.
   - **IP Access List**: To allow HuggingFace Spaces to connect, add `0.0.0.0/0` (Allow Access from Anywhere) to your IP access list. *(Note: HuggingFace Spaces use dynamic IP ranges, so allowing global access is required. Atlas protects your cluster using your database user authentication).*
4. **Get Connection String**:
   - Go to the **Database** dashboard.
   - Click **Connect** next to your cluster.
   - Select **Drivers** under the "Connect to your application" options.
   - Select **Python** as the driver.
   - Copy the connection string. It will look like:
     ```text
     mongodb+srv://fly_user:<db_password>@cluster0.xxxxxx.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0
     ```
   - Replace `<db_password>` with the password you generated for the database user.

---

## 2. Render Backend Deployment

Render is a fully managed cloud hosting platform. Its free tier does **not** require a credit card and can host Python web services out of the box.

1. **Sign Up / Log In**:
   - Go to [Render](https://render.com/) and register for a free account.
2. **Create a New Web Service**:
   - On the Render dashboard, click **New +** and select **Web Service**.
   - Connect your GitHub repository containing the backend code.
3. **Configure the Service**:
   - **Name**: e.g., `bitsathy-flylock`
   - **Language**: `Python`
   - **Branch**: `main`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python server.py 10000` *(Render routes traffic to port 10000 or the port specified in environment variables)*
   - **Plan**: Select **Free**.
4. **Configure Environment Variables**:
   - Go to the **Environment** tab of your Render Web Service.
   - Click **Add Environment Variable**:
     - **Key**: `MONGO_URI`
     - **Value**: Paste your MongoDB connection string (e.g. `mongodb+srv://mageesharavinds_db_user:HZaqDEb5rGcxL5NT@fly-cluster.79ubwoi.mongodb.net/?appName=Fly-cluster`)
   - Click **Save Changes**.
5. **Monitor Deploy Status**:
   - Render will start building the container and start running the server.
   - Once successfully deployed, Render will provide a public URL:
     ```text
     https://<service-name>.onrender.com
     ```
     *(Example: `https://bitsathy-flylock.onrender.com`)*
   - *Note: Free Render web services auto-sleep after 15 minutes of inactivity. When a new request arrives, it takes about 50 seconds to boot up.*

---

## 3. GitHub Pages Frontend Deployment

We will deploy the static asset files in the `public/` directory to GitHub Pages.

1. **Create GitHub Repository**:
   - Create a new repository on GitHub (e.g., `fly-frontend`).
2. **Push static assets**:
   - Initialize git in the `public/` directory and push it to your new repository:
     ```bash
     cd public
     git init
     git add .
     git commit -m "Deploy frontend to GitHub Pages"
     git branch -M main
     git remote add origin https://github.com/<your-username>/fly-frontend.git
     git push -u origin main --force
     ```
3. **Enable GitHub Pages**:
   - Go to your repository settings on GitHub.
   - In the sidebar, select **Pages**.
   - Under **Build and deployment**, select **Deploy from a branch**.
   - Choose the **main** branch and folder `/ (root)`.
   - Click **Save**.
   - In a few minutes, GitHub will publish your page to:
     ```text
     https://<your-username>.github.io/fly-frontend/
     ```

---

## 4. Connecting Frontend to Hugging Face Backend

1. **Setting the URL**:
   - Open your deployed GitHub Pages frontend in a web browser.
   - When running on `*.github.io`, the frontend will automatically attempt to connect to the default Hugging Face backend (`https://bitsathy-flylock.hf.space`).
   - If your Hugging Face Space URL is different, click the **⚙️ Settings Icon** in the bottom-right corner of the login screen or student dashboard.
   - Enter your actual Hugging Face Space backend URL.
   - The frontend will save this URL in `localStorage` and automatically route all API requests to it!
