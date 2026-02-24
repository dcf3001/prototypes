const express = require('express');
const cors = require('cors');
const path = require('path');
const alertsRouter = require('./routes/alerts');

const app = express();
const PORT = process.env.PORT || 3003;

app.use(cors());
app.use(express.json());

app.use('/api', alertsRouter);

// In production, serve the Vite build from client/dist
if (process.env.NODE_ENV === 'production') {
  const clientDist = path.join(__dirname, '../../client/dist');
  app.use(express.static(clientDist));
  app.get('*', (req, res) => {
    res.sendFile(path.join(clientDist, 'index.html'));
  });
}

app.listen(PORT, () => {
  console.log(`Physical Risk server running on http://localhost:${PORT}`);
});
