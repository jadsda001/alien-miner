# Alien Worlds Mining Bot - Koyeb Docker Deployment

High-performance Alien Worlds mining bot with C-based Proof-of-Work nonce finder.

## Features

- ⚡ **Fast PoW**: C-based nonce finder (~10-20x faster than JavaScript)
- 🌐 **Web Dashboard**: Control mining via browser
- 🐳 **Docker Ready**: Deploy to Koyeb, Railway, Render, etc.
- 🔒 **Secure**: Private keys stored in environment variables

## Quick Deploy to Koyeb

### 1. Push to GitHub

```bash
git add .
git commit -m "Koyeb deployment"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

### 2. Create Koyeb Service

1. Go to [app.koyeb.com](https://app.koyeb.com)
2. **Create Service** → **GitHub**
3. Select your repository
4. Configure:
   - **Instance**: Eco (Free) or Standard
   - **Port**: 8000
   - **Environment Variables**:
     - `BOT_CONFIG`: Your accounts (format below)
     - `PORT`: 8000

### 3. BOT_CONFIG Format

```
name:privateKey:cooldown,name:privateKey:cooldown,...
```

Example:
```
account1:5Kxxx...:7000,account2:5Kxxx...:2800,account3:5Kxxx...:2800
```

- First account = CPU Helper (doesn't mine, pays CPU)
- Cooldown in seconds (default: 2800)

## Local Development

```bash
# Install dependencies
npm install
pip install -r requirements.txt

# Run
python mine_web.py
```

Open `http://localhost:5000` and click **START ALL**.

## Files

| File | Description |
|------|-------------|
| `mine_web.py` | Flask web server + mining logic |
| `pow_worker.c` | C PoW nonce finder (compiled in Docker) |
| `pow_worker.js` | JavaScript fallback PoW |
| `sign.js` | EOSJS transaction signing |
| `Dockerfile` | Multi-stage build |

## License

MIT
