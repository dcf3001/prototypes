import React, { useRef, useEffect } from 'react';
import { MapContainer, TileLayer, GeoJSON, useMap } from 'react-leaflet';
import SeverityLegend from './SeverityLegend.jsx';
import StateLayer from './StateLayer.jsx';
import { severityColor } from '../hooks/useAlerts.js';
import { STATE_CENTROIDS } from '../constants/stateCentroids.js';

// Flies map to the selected alert's location.
// Polygon alerts → flyToBounds. Zone-only alerts → state centroid at zoom 7.
function FlyController({ selected }) {
  const map = useMap();

  useEffect(() => {
    if (!selected) return;

    if (selected.geometry) {
      try {
        const layer = window.L.geoJSON(selected.geometry);
        const bounds = layer.getBounds();
        if (bounds.isValid()) {
          map.flyToBounds(bounds, { padding: [60, 60], maxZoom: 9, duration: 1.2 });
        }
      } catch {}
    } else {
      // Zone-only: derive state from first SAME code and fly to centroid
      const sames = selected.properties?.geocode?.SAME || [];
      for (const same of sames) {
        if (same.length !== 6) continue;
        const stateFips = same.slice(1, 3);
        const centroid = STATE_CENTROIDS[stateFips];
        if (centroid) {
          map.flyTo([centroid.lat, centroid.lng], 7, { duration: 1.2 });
          break;
        }
      }
    }
  }, [selected, map]);

  return null;
}

// County layer uses a ref so the 3MB GeoJSON is never remounted — only restyled.
function CountyLayer({ countiesGeoJSON, fipsColorMap }) {
  const geoRef = useRef(null);

  useEffect(() => {
    if (geoRef.current) {
      geoRef.current.resetStyle();
    }
  }, [fipsColorMap]);

  const style = (feature) => {
    const color = fipsColorMap[feature.id];
    if (color) {
      return { fillColor: color, fillOpacity: 0.45, color, weight: 0.5, opacity: 0.7 };
    }
    return { fillColor: 'transparent', fillOpacity: 0, color: '#ccc', weight: 0.3, opacity: 0.35 };
  };

  return <GeoJSON ref={geoRef} data={countiesGeoJSON} style={style} />;
}

export default function RiskMap({ polygonAlerts, fipsColorMap, stateAlertMap, countiesGeoJSON, selected, onSelectAlert }) {
  // Key on alert IDs so polygon layer remounts when data changes
  const polygonKey = polygonAlerts.map(f => f.id).join(',');

  const polygonStyle = (feature) => {
    const color = severityColor(feature.properties?.severity);
    return { fillColor: color, fillOpacity: 0.4, color, weight: 2, opacity: 0.85 };
  };

  const onEachPolygon = (feature, layer) => {
    const p = feature.properties || {};
    layer.bindTooltip(
      `<strong>${p.event}</strong><br/>${p.areaDesc}`,
      { sticky: true }
    );
    layer.on('click', () => onSelectAlert(feature));
  };

  return (
    <div style={{ flex: 1, position: 'relative' }}>
      <MapContainer
        center={[39.5, -98.35]}
        zoom={4}
        style={{ height: '100%', width: '100%' }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {countiesGeoJSON && (
          <CountyLayer countiesGeoJSON={countiesGeoJSON} fipsColorMap={fipsColorMap} />
        )}

        {polygonAlerts.length > 0 && (
          <GeoJSON
            key={polygonKey}
            data={{ type: 'FeatureCollection', features: polygonAlerts }}
            style={polygonStyle}
            onEachFeature={onEachPolygon}
          />
        )}

        <StateLayer stateAlertMap={stateAlertMap} />

        <FlyController selected={selected} />
      </MapContainer>

      <SeverityLegend />
    </div>
  );
}
