import React, { useState } from 'react';
import { Marker, Tooltip, useMapEvents } from 'react-leaflet';
import L from 'leaflet';
import { STATE_CENTROIDS } from '../constants/stateCentroids.js';
import { SEVERITY_COLORS, worstSeverity } from '../hooks/useAlerts.js';

export default function StateLayer({ stateAlertMap }) {
  const [zoom, setZoom] = useState(4);

  useMapEvents({
    zoomend: (e) => setZoom(e.target.getZoom()),
  });

  // Hide individual state badges when zoomed in — county detail takes over
  if (zoom > 7) return null;

  return (
    <>
      {Object.entries(stateAlertMap).map(([fips, { count, severities }]) => {
        const centroid = STATE_CENTROIDS[fips];
        if (!centroid) return null;

        const severity = worstSeverity(severities);
        const color = SEVERITY_COLORS[severity] || SEVERITY_COLORS.Unknown;

        const size = Math.max(28, Math.min(44, 24 + count * 2));

        const icon = L.divIcon({
          className: '',
          html: `<div style="
            background: ${color};
            color: white;
            border-radius: 50%;
            width: ${size}px;
            height: ${size}px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: ${size > 36 ? 13 : 11}px;
            border: 2px solid rgba(255,255,255,0.85);
            box-shadow: 0 2px 6px rgba(0,0,0,0.35);
            pointer-events: auto;
          ">${count}</div>`,
          iconSize: [size, size],
          iconAnchor: [size / 2, size / 2],
        });

        return (
          <Marker key={fips} position={[centroid.lat, centroid.lng]} icon={icon}>
            <Tooltip direction="top" offset={[0, -size / 2 - 4]}>
              <strong>{centroid.name}</strong>: {count} active alert{count !== 1 ? 's' : ''}
            </Tooltip>
          </Marker>
        );
      })}
    </>
  );
}
