/** Shared-origin business storage. The preview gateway supplies the project ID. */
const projectId = document.querySelector<HTMLMetaElement>('meta[name="myatom-project-id"]')?.content
if (!projectId || !/^[0-9a-f]{32}$/.test(projectId)) {
  throw new Error('缺少可信的项目预览上下文，无法保存数据')
}

const prefix = `myatom.app.${projectId}.`
const keyPattern = /^[A-Za-z][A-Za-z0-9_.-]{0,79}$/

function scopedKey(key: string): string {
  if (!keyPattern.test(key)) throw new Error('数据键名无效')
  return prefix + key
}

export const generatedAppStorage = {
  getItem(key: string): string | null {
    return window.localStorage.getItem(scopedKey(key))
  },
  setItem(key: string, value: string): void {
    window.localStorage.setItem(scopedKey(key), value)
  },
  removeItem(key: string): void {
    window.localStorage.removeItem(scopedKey(key))
  },
}
