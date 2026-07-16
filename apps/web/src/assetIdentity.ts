import type { AssetRef } from './api';

interface AssetIdentityCarrier {
  asset_ref?: AssetRef | null;
}

export function getAssetIdentity(asset: AssetIdentityCarrier, legacyIdentity: string): string {
  return asset.asset_ref?.asset.asset_id || legacyIdentity;
}
