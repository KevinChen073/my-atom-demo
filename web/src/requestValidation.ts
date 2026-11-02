export function canSubmitNewRunRequest(request: string, hasActiveVersion: boolean): boolean {
  return request.trim().length >= (hasActiveVersion ? 1 : 10)
}
