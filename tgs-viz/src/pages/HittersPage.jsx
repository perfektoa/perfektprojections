import React, { useState, useMemo } from 'react';
import PlayerTable from '../components/PlayerTable';
import PlayerDetail from '../components/PlayerDetail';
import { HITTER_COLUMN_GROUPS } from '../lib/columns';
import { usePlayersWithFV, usePlayersWithDraftFV, usePlayersWithG5FV, usePlayersWithHybridFV, useHittersWithMarketValue } from '../hooks/usePlayerData';
import { formatMoney } from '../lib/marketValue';

export default function HittersPage({ players, isDraft = false, isFA = false, allPlayers, marketRate }) {
  const [selectedPlayer, setSelectedPlayer] = useState(null);
  const playersWithFV = usePlayersWithFV(players);

  // Compute Draft FV for all players when allPlayers is available
  const playersWithDraftFV = usePlayersWithDraftFV(
    allPlayers ? playersWithFV : [],
    allPlayers || [],
    'hitter'
  );

  // Compute G5 FV (devPercentile-based peak WAA)
  const afterDraft = playersWithDraftFV.length > 0 ? playersWithDraftFV : playersWithFV;
  const playersWithG5 = usePlayersWithG5FV(afterDraft, allPlayers || players, 'hitter');

  // Compute Hybrid FV (combines FV + G5 + Draft FV)
  const playersWithHybrid = usePlayersWithHybridFV(playersWithG5);

  // Compute market value ($/WAA, offer range, surplus)
  const finalPlayers = useHittersWithMarketValue(playersWithHybrid, marketRate);
  const rate = marketRate?.rate || 0;
  const lowConfidence = marketRate?.lowConfidence;

  const defaultGroups = isFA
    ? ['info', 'value', 'futureValue', 'marketCurrent', 'marketFuture']
    : ['info', 'value', 'futureValue', 'draftValue'];

  return (
    <div className="h-full flex flex-col">
      <div className="p-4 pb-2">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white">
              {isDraft ? 'Draft Hitters' : isFA ? 'Free Agent Hitters' : 'Hitters'}
            </h1>
            <p className="text-sm text-slate-400 mt-1">
              {players.length} players | Toggle column groups to explore data | Click a player for details
            </p>
          </div>
          {rate > 0 && (
            <div className="text-right">
              <p className="text-xs text-slate-500">$/WAA {lowConfidence && '⚠️'}</p>
              <p className={`text-sm font-semibold ${lowConfidence ? 'text-orange-400' : 'text-green-400'}`}>{formatMoney(rate)}</p>
              {lowConfidence && <p className="text-[10px] text-orange-400">Low data — WAA not populated for most players</p>}
            </div>
          )}
        </div>
      </div>

      <div className="flex-1 min-h-0">
        <PlayerTable
          players={finalPlayers}
          columnGroups={HITTER_COLUMN_GROUPS}
          defaultActiveGroups={defaultGroups}
          onPlayerClick={setSelectedPlayer}
          selectedPlayerId={selectedPlayer?.ID}
          maxRows={1000}
          positionViewMode
        />
      </div>

      {selectedPlayer && (
        <PlayerDetail
          player={selectedPlayer}
          onClose={() => setSelectedPlayer(null)}
          type="hitter"
        />
      )}
    </div>
  );
}
