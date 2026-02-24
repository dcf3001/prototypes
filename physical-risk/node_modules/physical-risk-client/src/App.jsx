import React, { useState } from 'react';
import { useAlerts, useCounties } from './hooks/useAlerts.js';
import HazardSelector from './components/HazardSelector.jsx';
import AlertSidebar from './components/AlertSidebar.jsx';
import RiskMap from './components/RiskMap.jsx';

export default function App() {
  const [selectedType, setSelectedType]   = useState(null);
  const [selectedAlert, setSelectedAlert] = useState(null);
  const [ianMode, setIanMode]             = useState(false);

  const handleToggleIan = () => {
    setIanMode(prev => !prev);
    setSelectedType(null);
    setSelectedAlert(null);
  };

  const { features, polygonAlerts, fipsColorMap, stateAlertMap, isLoading, isError, totalCount } =
    useAlerts(selectedType, ianMode ? 'ian' : null);

  const { data: countiesGeoJSON } = useCounties();

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', fontFamily: 'system-ui, sans-serif', overflow: 'hidden' }}>

      {/* Header */}
      <div style={{
        background: ianMode ? '#4a148c' : '#1a237e',
        color: '#fff',
        padding: '0 16px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexShrink: 0,
        minHeight: 48,
        transition: 'background 0.3s',
      }}>
        <div style={{ fontWeight: 700, fontSize: 16, letterSpacing: 0.3 }}>
          US Physical Risk Dashboard
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <div style={{ fontSize: 12, opacity: 0.8 }}>
            {isLoading && 'Loading alerts…'}
            {isError  && 'Error fetching alerts'}
            {!isLoading && !isError && `${totalCount} active alert${totalCount !== 1 ? 's' : ''}${!ianMode ? ' · auto-refresh 5 min' : ''}`}
          </div>

          <button
            onClick={handleToggleIan}
            title={ianMode ? 'Return to live NOAA data' : 'View historical snapshot: Hurricane Ian (Sep 28 2022)'}
            style={{
              padding: '5px 12px',
              borderRadius: 20,
              border: ianMode ? '2px solid #ce93d8' : '1.5px solid rgba(255,255,255,0.5)',
              background: ianMode ? '#7b1fa2' : 'transparent',
              color: '#fff',
              cursor: 'pointer',
              fontSize: 12,
              fontWeight: 600,
              whiteSpace: 'nowrap',
              transition: 'all 0.2s',
            }}
          >
            {ianMode ? '← Live Data' : 'Hurricane Ian (Sep 28, 2022)'}
          </button>
        </div>
      </div>

      {/* Historical banner */}
      {ianMode && (
        <div style={{
          background: '#f3e5f5',
          borderBottom: '2px solid #7b1fa2',
          padding: '6px 16px',
          fontSize: 12,
          color: '#4a148c',
          fontWeight: 600,
          flexShrink: 0,
        }}>
          Historical snapshot — Hurricane Ian landfall · Fort Myers, FL · Sep 28, 2022 ~3:05 PM EDT
          {' '}· Simulated representative alert data · not real-time
        </div>
      )}

      {/* Filter bar */}
      <div style={{ background: '#fff', borderBottom: '1px solid #ddd', flexShrink: 0 }}>
        <HazardSelector selected={selectedType} onSelect={setSelectedType} historicalPreset={ianMode ? 'ian' : null} />
      </div>

      {/* Main content */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <AlertSidebar
          features={features}
          selected={selectedAlert}
          onSelect={setSelectedAlert}
        />
        <RiskMap
          polygonAlerts={polygonAlerts}
          fipsColorMap={fipsColorMap}
          stateAlertMap={stateAlertMap}
          countiesGeoJSON={countiesGeoJSON}
          selected={selectedAlert}
          onSelectAlert={setSelectedAlert}
        />
      </div>
    </div>
  );
}
