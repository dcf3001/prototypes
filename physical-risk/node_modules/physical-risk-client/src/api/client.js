import axios from 'axios';

const api = axios.create({ baseURL: '/api' });

export async function getAlerts() {
  const { data } = await api.get('/alerts');
  return data;
}

export async function getAlertTypes() {
  const { data } = await api.get('/alerts/types');
  return data;
}

export async function getHistoricalAlerts(preset = 'ian') {
  const { data } = await api.get(`/alerts/historical?preset=${preset}`);
  return data;
}

export async function getCounties() {
  const { data } = await api.get('/counties');
  return data;
}
