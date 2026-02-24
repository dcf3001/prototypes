const express = require('express');
const path = require('path');
const router = express.Router();

const NOAA_ALERTS_URL = 'https://api.weather.gov/alerts/active';

const HISTORICAL_PRESETS = {
  ian: require(path.join(__dirname, '../../data/ian_alerts.json')),
};
const COUNTIES_URL = 'https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json';

const NOAA_HEADERS = {
  'User-Agent': '(PhysicalRiskDashboard, dev@localapp.com)',
  'Accept': 'application/geo+json',
};

const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes

let alertsCache = null;
let alertsCacheTime = 0;

let countiesCache = null;

// GET /api/alerts
router.get('/alerts', async (req, res) => {
  const now = Date.now();
  if (alertsCache && now - alertsCacheTime < CACHE_TTL_MS) {
    return res.json(alertsCache);
  }

  try {
    const response = await fetch(NOAA_ALERTS_URL, { headers: NOAA_HEADERS });
    if (!response.ok) {
      throw new Error(`NOAA returned ${response.status}`);
    }
    const data = await response.json();
    alertsCache = data;
    alertsCacheTime = now;
    res.json(data);
  } catch (err) {
    console.error('NOAA fetch error:', err.message);
    if (alertsCache) {
      // Serve stale on error
      return res.json(alertsCache);
    }
    res.status(502).json({ error: 'Failed to fetch alerts from NOAA', details: err.message });
  }
});

// GET /api/alerts/types — must be defined BEFORE any :id wildcard
router.get('/alerts/types', async (req, res) => {
  const now = Date.now();
  // Refresh cache if stale
  if (!alertsCache || now - alertsCacheTime >= CACHE_TTL_MS) {
    try {
      const response = await fetch(NOAA_ALERTS_URL, { headers: NOAA_HEADERS });
      if (response.ok) {
        const data = await response.json();
        alertsCache = data;
        alertsCacheTime = now;
      }
    } catch (err) {
      console.error('NOAA fetch error (types):', err.message);
    }
  }

  if (!alertsCache) {
    return res.json([]);
  }

  const features = alertsCache.features || [];
  const typeCounts = {};
  for (const f of features) {
    const event = f.properties?.event || 'Unknown';
    typeCounts[event] = (typeCounts[event] || 0) + 1;
  }

  const types = Object.entries(typeCounts)
    .sort((a, b) => b[1] - a[1])
    .map(([event, count]) => ({ event, count }));

  res.json(types);
});

// GET /api/alerts/historical?preset=ian — static snapshot, must be before :id wildcard
router.get('/alerts/historical', (req, res) => {
  const preset = req.query.preset || 'ian';
  const data = HISTORICAL_PRESETS[preset];
  if (!data) {
    return res.status(404).json({ error: `Unknown preset: ${preset}` });
  }
  res.json(data);
});

// GET /api/counties — fetched once, cached permanently
router.get('/counties', async (req, res) => {
  if (countiesCache) {
    return res.json(countiesCache);
  }

  try {
    const response = await fetch(COUNTIES_URL);
    if (!response.ok) {
      throw new Error(`Counties fetch returned ${response.status}`);
    }
    const data = await response.json();
    countiesCache = data;
    res.json(data);
  } catch (err) {
    console.error('Counties fetch error:', err.message);
    res.status(502).json({ error: 'Failed to fetch counties GeoJSON', details: err.message });
  }
});

module.exports = router;
