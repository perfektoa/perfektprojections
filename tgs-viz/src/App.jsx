import React, { useState, useEffect, useMemo } from 'react';
import { Routes, Route, NavLink, Navigate } from 'react-router-dom';
import { usePlayerData, useLeagues, useMarketRate } from './hooks/usePlayerData';
import HittersPage from './pages/HittersPage';
import PitchersPage from './pages/PitchersPage';
import DraftBoardPage from './pages/DraftBoardPage';
import RosterOptimizerPage from './pages/RosterOptimizerPage';
import DevAnalysisPage from './pages/DevAnalysisPage';
import MarketValuePage from './pages/MarketValuePage';
import TeamStandingsPage from './pages/TeamStandingsPage';
import { Users, Zap, Target, Trophy, Loader2, AlertCircle, BarChart3, TrendingUp, ChevronDown, DollarSign, TableProperties } from 'lucide-react';

function Sidebar({ leagues, currentLeague, onLeagueChange }) {
  const linkClass = ({ isActive }) =>
    `flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-sm font-medium transition-all ${
      isActive
        ? 'bg-blue-600/20 text-blue-400 border-l-2 border-blue-400'
        : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
    }`;

  return (
    <nav className="w-56 bg-slate-900 border-r border-slate-800 flex flex-col h-full">
      <div className="p-4 border-b border-slate-800">
        <h1 className="text-lg font-black text-white tracking-tight">TGS</h1>
        <p className="text-[10px] text-slate-500 uppercase tracking-widest">Projections Viz</p>
      </div>

      {/* League Switcher */}
      {leagues.length > 1 && (
        <div className="px-3 pt-3 pb-1">
          <p className="text-[10px] text-slate-600 uppercase tracking-widest px-1 pb-1.5">League</p>
          <div className="relative">
            <select
              value={currentLeague}
              onChange={(e) => onLeagueChange(e.target.value)}
              className="w-full appearance-none bg-slate-800 text-white text-sm font-semibold rounded-lg px-3 py-2 pr-8 border border-slate-700 hover:border-blue-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 transition-colors cursor-pointer"
            >
              {leagues.map(lg => (
                <option key={lg.id} value={lg.id}>{lg.name}</option>
              ))}
            </select>
            <ChevronDown size={14} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
          </div>
        </div>
      )}

      <div className="flex-1 p-2 space-y-0.5">
        <p className="text-[10px] text-slate-600 uppercase tracking-widest px-3 pt-3 pb-1">Team Sheets</p>
        <NavLink to="/hitters" className={linkClass}>
          <Users size={16} /> Hitters
        </NavLink>
        <NavLink to="/pitchers" className={linkClass}>
          <Zap size={16} /> Pitchers
        </NavLink>

        <p className="text-[10px] text-slate-600 uppercase tracking-widest px-3 pt-4 pb-1">Draft</p>
        <NavLink to="/hitters-draft" className={linkClass}>
          <Users size={16} /> Hitters (Draft)
        </NavLink>
        <NavLink to="/pitchers-draft" className={linkClass}>
          <Zap size={16} /> Pitchers (Draft)
        </NavLink>
        <NavLink to="/draft-board" className={linkClass}>
          <BarChart3 size={16} /> Draft Board
        </NavLink>

        <p className="text-[10px] text-slate-600 uppercase tracking-widest px-3 pt-4 pb-1">Free Agency</p>
        <NavLink to="/hitters-fa" className={linkClass}>
          <Users size={16} /> Hitters (FA)
        </NavLink>
        <NavLink to="/pitchers-fa" className={linkClass}>
          <Zap size={16} /> Pitchers (FA)
        </NavLink>

        <p className="text-[10px] text-slate-600 uppercase tracking-widest px-3 pt-4 pb-1">Standings</p>
        <NavLink to="/standings" className={linkClass}>
          <TableProperties size={16} /> Team Projections
        </NavLink>

        <p className="text-[10px] text-slate-600 uppercase tracking-widest px-3 pt-4 pb-1">Tools</p>
        <NavLink to="/market-value" className={linkClass}>
          <DollarSign size={16} /> Market Value
        </NavLink>
        <NavLink to="/optimizer" className={linkClass}>
          <Trophy size={16} /> Roster Optimizer
        </NavLink>
        <NavLink to="/dev-analysis" className={linkClass}>
          <TrendingUp size={16} /> Dev Analysis
        </NavLink>
      </div>
      <div className="p-3 border-t border-slate-800 text-[10px] text-slate-600">
        OOTP 26 Analytics
      </div>
    </nav>
  );
}

function LoadingScreen({ progress, league }) {
  return (
    <div className="flex items-center justify-center h-screen bg-slate-950">
      <div className="text-center space-y-4">
        <Loader2 size={48} className="animate-spin text-blue-500 mx-auto" />
        <div>
          <h2 className="text-xl font-bold text-white">Loading Player Data</h2>
          <p className="text-sm text-slate-400 mt-1">
            {league ? `Loading ${league} league...` : 'Processing thousands of players...'}
          </p>
        </div>
        <div className="space-y-1.5 text-left">
          {Object.entries(progress).map(([key, status]) => (
            <div key={key} className="flex items-center gap-2 text-sm">
              <span className={`w-2 h-2 rounded-full ${
                status === 'loaded' ? 'bg-green-400' :
                status === 'loading' ? 'bg-blue-400 animate-pulse' :
                status === 'error' ? 'bg-red-400' :
                'bg-slate-600'
              }`} />
              <span className="text-slate-400 capitalize">{key.replace(/_/g, ' ')}</span>
              <span className="text-xs text-slate-600">{status}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ErrorScreen({ error }) {
  return (
    <div className="flex items-center justify-center h-screen bg-slate-950">
      <div className="text-center space-y-4 max-w-md">
        <AlertCircle size={48} className="text-red-400 mx-auto" />
        <div>
          <h2 className="text-xl font-bold text-white">Error Loading Data</h2>
          <p className="text-sm text-red-400 mt-2">{error}</p>
        </div>
        <div className="text-sm text-slate-400 bg-slate-900 rounded-lg p-4 text-left">
          <p className="font-semibold text-slate-300 mb-2">Make sure you've run the data extractor:</p>
          <code className="text-blue-400 text-xs block bg-slate-800 p-2 rounded">
            cd tgs-viz && python extract_data.py
          </code>
          <p className="mt-2 text-xs">This extracts data from all "The Sheets *" folders into JSON files that the web app reads.</p>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  // Load the leagues manifest
  const { leagues, loading: leaguesLoading, error: leaguesError } = useLeagues();

  // League selection — persisted in localStorage
  const [currentLeague, setCurrentLeague] = useState(() => {
    return localStorage.getItem('tgs-league') || '';
  });

  // When leagues load, ensure we have a valid selection
  useEffect(() => {
    if (leagues.length > 0) {
      const saved = localStorage.getItem('tgs-league');
      const isValid = leagues.some(lg => lg.id === saved);
      if (!isValid) {
        // Default to first league
        setCurrentLeague(leagues[0].id);
        localStorage.setItem('tgs-league', leagues[0].id);
      }
    }
  }, [leagues]);

  const handleLeagueChange = (leagueId) => {
    setCurrentLeague(leagueId);
    localStorage.setItem('tgs-league', leagueId);
  };

  // Load player data for the selected league
  const { data, loading, error, loadProgress } = usePlayerData(currentLeague);

  // Compute league-wide $/WAA rate (must be before early returns — React hooks rule)
  const marketRate = useMarketRate(data.hitters, data.pitchers);

  // Show loading while leagues manifest loads
  if (leaguesLoading) return <LoadingScreen progress={{}} league="" />;
  if (leaguesError) return <ErrorScreen error={leaguesError} />;
  if (leagues.length === 0) return <ErrorScreen error="No leagues found. Run python extract_data.py first." />;

  // Show loading while player data loads
  if (loading) return <LoadingScreen progress={loadProgress} league={currentLeague} />;
  if (error) return <ErrorScreen error={error} />;

  const hasData = data.hitters.length > 0 || data.pitchers.length > 0;

  if (!hasData) {
    return <ErrorScreen error={`No player data found for league "${currentLeague}". Run python extract_data.py first.`} />;
  }

  return (
    <div className="flex h-screen bg-slate-950">
      <Sidebar
        leagues={leagues}
        currentLeague={currentLeague}
        onLeagueChange={handleLeagueChange}
      />
      <main className="flex-1 overflow-hidden">
        <div className="gradient-bar" />
        <div className="h-[calc(100%-3px)]">
          <Routes>
            <Route path="/" element={<Navigate to="/hitters" replace />} />
            <Route path="/hitters" element={<HittersPage players={data.hitters} allPlayers={data.hitters} marketRate={marketRate} />} />
            <Route path="/pitchers" element={<PitchersPage players={data.pitchers} allPlayers={data.pitchers} marketRate={marketRate} />} />
            <Route path="/hitters-draft" element={<HittersPage players={data.hitters_draft} isDraft allPlayers={data.hitters} marketRate={marketRate} />} />
            <Route path="/pitchers-draft" element={<PitchersPage players={data.pitchers_draft} isDraft allPlayers={data.pitchers} marketRate={marketRate} />} />
            <Route path="/hitters-fa" element={<HittersPage players={data.hitters_fa.length ? data.hitters_fa : data.hitters} isFA allPlayers={data.hitters} marketRate={marketRate} />} />
            <Route path="/pitchers-fa" element={<PitchersPage players={data.pitchers_fa.length ? data.pitchers_fa : data.pitchers} isFA allPlayers={data.pitchers} marketRate={marketRate} />} />
            <Route path="/draft-board" element={
              <DraftBoardPage
                hitters={data.hitters_draft.length ? data.hitters_draft : data.hitters}
                pitchers={data.pitchers_draft.length ? data.pitchers_draft : data.pitchers}
                allHitters={data.hitters}
                allPitchers={data.pitchers}
              />
            } />
            <Route path="/standings" element={
              <TeamStandingsPage hitters={data.hitters} pitchers={data.pitchers} />
            } />
            <Route path="/market-value" element={
              <MarketValuePage hitters={data.hitters} pitchers={data.pitchers} />
            } />
            <Route path="/optimizer" element={
              <RosterOptimizerPage hitters={data.hitters} pitchers={data.pitchers} />
            } />
            <Route path="/dev-analysis" element={<DevAnalysisPage />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
