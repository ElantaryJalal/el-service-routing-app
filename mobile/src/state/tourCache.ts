/**
 * Offline cache for the composed optimised tour. Written whenever optimise runs
 * (from the Review screen) so the Map, day filter, and detail cards keep working
 * with no network. Keyed by tour id in AsyncStorage.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';

import type { OptimisedTour } from '../domain/optimisedTour';

const key = (tourId: number) => `optimisedTour:${tourId}`;

export const tourCache = {
  async save(tour: OptimisedTour): Promise<void> {
    await AsyncStorage.setItem(key(tour.tour_id), JSON.stringify(tour));
  },

  async load(tourId: number): Promise<OptimisedTour | null> {
    const raw = await AsyncStorage.getItem(key(tourId));
    if (!raw) return null;
    try {
      return JSON.parse(raw) as OptimisedTour;
    } catch {
      return null;
    }
  },

  async clear(tourId: number): Promise<void> {
    await AsyncStorage.removeItem(key(tourId));
  },
};
