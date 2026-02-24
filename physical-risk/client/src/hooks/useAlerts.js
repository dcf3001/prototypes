import { useQuery } from '@tanstack/react-query';
import { getAlerts, getHistoricalAlerts, getCounties } from '../api/client.js';

export const SEVERITY_COLORS = {
  Extreme:  '#d32f2f',
  Severe:   '#e65100',
  Moderate: '#f9a825',
  Minor:    '#0277bd',
  Unknown:  '#757575',
};

const SEVERITY_ORDER = { Extreme: 0, Severe: 1, Moderate: 2, Minor: 3, Unknown: 99 };

export function severityColor(severity) {
  return SEVERITY_COLORS[severity] || SEVERITY_COLORS.Unknown;
}

export function worstSeverity(severities) {
  return severities.reduce((best, s) => {
    return (SEVERITY_ORDER[s] ?? 99) < (SEVERITY_ORDER[best] ?? 99) ? s : best;
  }, 'Unknown');
}

export function useAlerts(selectedType, historicalPreset = null) {
  const isHistorical = historicalPreset != null;

  const { data, isLoading, isError, dataUpdatedAt } = useQuery({
    queryKey: ['alerts', isHistorical ? historicalPreset : 'live'],
    queryFn: isHistorical ? () => getHistoricalAlerts(historicalPreset) : getAlerts,
    refetchInterval: isHistorical ? false : 5 * 60 * 1000,
    staleTime: isHistorical ? Infinity : 4 * 60 * 1000,
  });

  const features = data?.features || [];

  const filtered = selectedType
    ? features.filter(f => f.properties?.event === selectedType)
    : features;

  // Split into polygon alerts vs zone-only alerts
  const polygonAlerts = filtered.filter(f => f.geometry != null);
  const zoneAlerts    = filtered.filter(f => f.geometry == null);

  // FIPS → color map for county layer (zone-only alerts)
  const fipsColorMap = {};
  for (const f of zoneAlerts) {
    const sames = f.properties?.geocode?.SAME || [];
    const color = severityColor(f.properties?.severity);
    for (const same of sames) {
      if (same.length !== 6) continue;
      const fips = same.slice(1); // "012071" → "12071"
      if (!fipsColorMap[fips]) fipsColorMap[fips] = color;
    }
  }

  // State FIPS → { count, severities[] } for state badge layer
  // Count each alert once per state (even if it covers multiple counties in that state)
  const stateAlertMap = {};
  for (const f of filtered) {
    const sames = f.properties?.geocode?.SAME || [];
    const severity = f.properties?.severity || 'Unknown';
    const seenStates = new Set();
    for (const same of sames) {
      if (same.length !== 6) continue;
      const stateFips = same.slice(1, 3);
      if (seenStates.has(stateFips)) continue;
      seenStates.add(stateFips);
      if (!stateAlertMap[stateFips]) stateAlertMap[stateFips] = { count: 0, severities: [] };
      stateAlertMap[stateFips].count++;
      stateAlertMap[stateFips].severities.push(severity);
    }
  }

  return {
    features: filtered,
    polygonAlerts,
    zoneAlerts,
    fipsColorMap,
    stateAlertMap,
    isLoading,
    isError,
    dataUpdatedAt,
    totalCount: features.length,
  };
}

export function useCounties() {
  return useQuery({
    queryKey: ['counties'],
    queryFn: getCounties,
    staleTime: Infinity,
    gcTime: Infinity,
  });
}
