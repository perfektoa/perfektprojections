import React, { useState, useEffect } from 'react';
import { BOARD_PARTS, BOARD_WEIGHTS } from '../lib/draftValue';

const toPct = w => Object.fromEntries(BOARD_PARTS.map(([k]) => [k, String(Math.round((w[k] || 0) * 100))]));

/**
 * Four weight boxes (in %) and a "Redo board" button. The typed numbers do
 * not have to add up to 100: they are scaled on apply. "Default" puts back
 * 40 / 20 / 20 / 20.
 */
export default function BoardWeights({ weights, onApply }) {
  const [draft, setDraft] = useState(() => toPct(weights));
  useEffect(() => { setDraft(toPct(weights)); }, [weights]);

  const sum = BOARD_PARTS.reduce((s, [k]) => s + (parseFloat(draft[k]) || 0), 0);
  const dirty = BOARD_PARTS.some(([k]) => (parseFloat(draft[k]) || 0) !== Math.round((weights[k] || 0) * 100));
  const apply = () => onApply(Object.fromEntries(BOARD_PARTS.map(([k]) => [k, parseFloat(draft[k]) || 0])));

  return (
    <div className="flex flex-wrap items-center gap-2 bg-slate-800 rounded-lg px-2 py-1" title="The Board score weights, in %. Type new ones and press Redo board.">
      <span className="text-xs text-slate-500">Board weights:</span>
      {BOARD_PARTS.map(([k, name, what]) => (
        <label key={k} className="flex items-center gap-1 text-xs text-slate-400" title={what}>
          {name}
          <input type="number" min="0" max="100" step="5" value={draft[k]}
            onChange={e => setDraft(d => ({ ...d, [k]: e.target.value }))}
            onKeyDown={e => { if (e.key === 'Enter') apply(); }}
            className="w-12 py-0.5 px-1 bg-slate-900 border border-slate-600 rounded text-sm text-slate-200 text-right" />
          <span className="text-slate-600">%</span>
        </label>
      ))}
      <button onClick={apply}
        className={`px-2 py-1 text-xs font-medium rounded-md ${dirty ? 'bg-blue-600 text-white' : 'bg-slate-700 text-slate-300'}`}>
        Redo board
      </button>
      <button onClick={() => onApply({ ...BOARD_WEIGHTS })} className="px-2 py-1 text-xs text-slate-400 hover:text-white">
        Default
      </button>
      {Math.round(sum) !== 100 && sum > 0 && (
        <span className="text-xs text-amber-400">adds up to {Math.round(sum)}%, scaled to 100 on Redo</span>
      )}
    </div>
  );
}
