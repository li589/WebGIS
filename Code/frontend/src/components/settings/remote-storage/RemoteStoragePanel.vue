<script setup lang="ts">
/**
 * RemoteStoragePanel — 远程存储源管理面板（「远程与存储」tab 之一）。
 *
 * 组成：ProfileForm（新增/编辑）+ ProfileCard 列表（测试/浏览/切主备/启停/历史/删除）
 *      + ProfileBrowserDialog（目录浏览/搜索/添加为远程数据源）。
 */

import { computed, reactive, ref } from 'vue'
import { storeToRefs } from 'pinia'
import type { RemoteStorageProfile } from '../../../types/api-reexports'
import { useSettingsStore } from '../../../stores/settings'
import ProfileForm from './ProfileForm.vue'
import ProfileCard from './ProfileCard.vue'
import ProfileBrowserDialog from './ProfileBrowserDialog.vue'

const settingsStore = useSettingsStore()
const { remoteStorageProfiles, remoteStorageHistory } = storeToRefs(settingsStore)

const editing = ref<RemoteStorageProfile | null>(null)

const browserVisible = ref(false)
const browserProfile = ref<RemoteStorageProfile | null>(null)

const historyOpen = reactive<Record<string, boolean>>({})
const historyLoading = reactive<Record<string, boolean>>({})

const sortedProfiles = computed(() =>
  [...remoteStorageProfiles.value].sort((a, b) => a.profile_id.localeCompare(b.profile_id)),
)

function onSaved() {
  void settingsStore.loadRemoteStorageProfiles()
}

function onCardChanged() {
  void settingsStore.loadRemoteStorageProfiles()
}

function startEdit(profile: RemoteStorageProfile) {
  editing.value = profile
  // 滚动到表单位置
  requestAnimationFrame(() => {
    document
      .querySelector('.remote-storage-panel')
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
}

function openBrowser(profile: RemoteStorageProfile) {
  browserProfile.value = profile
  browserVisible.value = true
}

async function toggle(profile: RemoteStorageProfile) {
  try {
    await settingsStore.toggleRemoteStorageProfileEnabled(profile.profile_id, !profile.enabled)
  } catch (e) {
    alert(`切换失败: ${(e as Error).message}`)
  }
}

async function remove(profile: RemoteStorageProfile) {
  if (!confirm(`确认删除远程存储源「${profile.profile_id}」？其历史凭据也将清除。`)) return
  try {
    await settingsStore.removeRemoteStorageProfile(profile.profile_id)
    if (editing.value?.profile_id === profile.profile_id) editing.value = null
  } catch (e) {
    alert(`删除失败: ${(e as Error).message}`)
  }
}

async function toggleHistory(profileId: string) {
  const open = !historyOpen[profileId]
  historyOpen[profileId] = open
  if (!open) return
  historyLoading[profileId] = true
  try {
    await settingsStore.loadRemoteStorageHistory(profileId)
  } catch (e) {
    alert(`加载历史失败: ${(e as Error).message}`)
  } finally {
    historyLoading[profileId] = false
  }
}

async function restoreHistory(profileId: string, historyId: number) {
  try {
    await settingsStore.restoreRemoteStorageFromHistory(profileId, historyId)
  } catch (e) {
    alert(`恢复失败: ${(e as Error).message}`)
  }
}

async function deleteHistory(profileId: string, historyId: number) {
  if (!confirm(`删除历史 #${historyId}？`)) return
  try {
    await settingsStore.removeRemoteStorageHistoryEntry(profileId, historyId)
    await settingsStore.loadRemoteStorageHistory(profileId)
  } catch (e) {
    alert(`删除失败: ${(e as Error).message}`)
  }
}
</script>

<template>
  <div class="remote-storage-panel">
    <section class="settings-section">
      <h3 class="section-title">远程存储源</h3>
      <p class="section-hint">
        支持 sftp / ssh / smb / ftp(s) / http(s) / filebrowser / 局域网共享 / nfs / gs 共 11
        种协议。 每个源可配「内网 + 隧道」双路径（主路径异常自动回退）；凭据加密保存在后端。 URI
        引用形如 <code>smb://host/share/path/file.h5?cred=profile_id</code>，
        工作流「远程拉取」节点用 <code>cred_profile</code> 引用。
      </p>
      <ProfileForm :editing="editing" @saved="onSaved" @switch-new="editing = null" />
    </section>

    <section class="settings-section">
      <h3 class="section-title">已配置源（{{ sortedProfiles.length }}）</h3>
      <div v-if="sortedProfiles.length === 0" class="empty">
        暂无远程存储源；使用上方表单创建第一个（如实验室 NAS、SSH 服务器或 FileBrowser）。
      </div>
      <div v-else class="card-list">
        <template v-for="item in sortedProfiles" :key="item.profile_id">
          <ProfileCard
            :profile="item"
            @edit="startEdit"
            @browse="openBrowser"
            @add-remote-source="openBrowser"
            @changed="onCardChanged"
          />
          <div class="card-extra" :class="{ disabled: !item.enabled }">
            <div class="actions">
              <button type="button" class="btn" @click="toggleHistory(item.profile_id)">
                {{ historyOpen[item.profile_id] ? '收起历史' : '凭据历史' }}
              </button>
              <button type="button" class="btn" @click="toggle(item)">
                {{ item.enabled ? '禁用' : '启用' }}
              </button>
              <button type="button" class="btn danger" @click="remove(item)">删除</button>
            </div>
            <div v-if="historyOpen[item.profile_id]" class="history-panel">
              <p v-if="historyLoading[item.profile_id]" class="history-empty">加载中…</p>
              <p
                v-else-if="!(remoteStorageHistory[item.profile_id] || []).length"
                class="history-empty"
              >
                暂无密钥历史（更新密码/私钥时会自动归档）
              </p>
              <ul v-else class="history-list">
                <li
                  v-for="row in remoteStorageHistory[item.profile_id]"
                  :key="row.id"
                  class="history-row"
                >
                  <span>
                    <code>{{ row.masked_secret || '****' }}</code>
                    · {{ row.has_private_key ? '含私钥' : '无私钥' }} · {{ row.superseded_at }}
                  </span>
                  <span class="history-actions">
                    <button
                      type="button"
                      class="btn"
                      @click="restoreHistory(item.profile_id, row.id)"
                    >
                      恢复
                    </button>
                    <button
                      type="button"
                      class="btn danger"
                      @click="deleteHistory(item.profile_id, row.id)"
                    >
                      删除
                    </button>
                  </span>
                </li>
              </ul>
            </div>
          </div>
        </template>
      </div>
    </section>

    <ProfileBrowserDialog
      :visible="browserVisible"
      :profile="browserProfile"
      @close="browserVisible = false"
      @added="onCardChanged"
    />
  </div>
</template>

<style scoped src="../settings-form.css"></style>
<style scoped>
.remote-storage-panel {
  display: flex;
  flex-direction: column;
  gap: 1.2rem;
}
.settings-section {
  display: flex;
  flex-direction: column;
  gap: 0.52rem;
}
.card-list {
  display: flex;
  flex-direction: column;
  gap: 0.52rem;
}
.card-extra {
  margin-top: -0.4rem;
  padding: 0 0.72rem 0.4rem;
}
.card-extra .actions {
  justify-content: flex-end;
  margin-top: 0;
}
.card-extra.disabled {
  opacity: 0.55;
}
.history-panel {
  margin-top: 0.45rem;
  padding-top: 0.4rem;
  border-top: 1px solid var(--border-subtle);
}
.history-empty {
  margin: 0;
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
}
.history-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.32rem;
}
.history-row {
  display: flex;
  justify-content: space-between;
  gap: 0.4rem;
  align-items: center;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
}
.history-row code {
  color: var(--text-primary);
}
.history-actions {
  display: flex;
  gap: 0.28rem;
}
</style>
