import { useState, useEffect, useCallback } from 'react';
import { loadBoardWeights, saveBoardWeights } from '../lib/draftValue';

/**
 * The Board score weights (draftValue.js): the saved set, or the defaults.
 * Every page using this hook sees a change made on any of them, and the set
 * survives a reload (browser storage).
 */
export function useBoardWeights() {
  const [weights, setWeights] = useState(loadBoardWeights);
  useEffect(() => {
    const onChange = e => setWeights(e.detail ? { ...e.detail } : loadBoardWeights());
    const onStorage = () => setWeights(loadBoardWeights());
    window.addEventListener('tgs:boardWeights', onChange);
    window.addEventListener('storage', onStorage);
    return () => {
      window.removeEventListener('tgs:boardWeights', onChange);
      window.removeEventListener('storage', onStorage);
    };
  }, []);
  const apply = useCallback(w => setWeights(saveBoardWeights(w)), []);
  return [weights, apply];
}
