import { useQuery } from '@tanstack/react-query'
import { get } from '@/lib/api'

export interface PublicConfig { app_name: string; version: string; demo_mode: boolean; demo_accounts: boolean; currency: string }

/** Unauthenticated deployment info (demo vs actual). */
export const usePublicConfig = () =>
  useQuery({ queryKey: ['public-config'], queryFn: () => get<PublicConfig>('/api/system/public'), staleTime: Infinity })
