import type { Dispatch, FormEvent, InputHTMLAttributes, SetStateAction } from 'react';
import { KeyRound, RefreshCw, Settings, UserPlus, Users, X } from 'lucide-react';

import type { LlmSettings, ManagedUser, UserContext } from '../api';
import { ActionButton, ManagementHeader, ManagementPage, ModalFrame } from './ui/ManagementUI';

export interface ManagedUserDraft {
  username: string;
  display_name: string;
  password: string;
  role: 'admin' | 'user';
}

interface SystemSettingsPageProps {
  userContext: UserContext;
  llmSettings: LlmSettings | null;
  llmBaseUrl: string;
  setLlmBaseUrl: (value: string) => void;
  llmModel: string;
  setLlmModel: (value: string) => void;
  llmApiKey: string;
  setLlmApiKey: (value: string) => void;
  llmTimeout: string;
  setLlmTimeout: (value: string) => void;
  isSavingLlm: boolean;
  isProbingLlm: boolean;
  llmProbe: { healthy: boolean; latency_ms: number; message: string } | null;
  onSaveLlm: (event: FormEvent) => void;
  onProbeLlm: () => void;
  managedUsers: ManagedUser[];
  onCreateUser: () => void;
  onEditUser: (user: ManagedUser) => void;
  onRoleChange: (username: string, role: 'admin' | 'user') => void;
  onDeleteUser: (username: string) => void;
  userModalOpen: boolean;
  editingUsername: string | null;
  userDraft: ManagedUserDraft;
  setUserDraft: Dispatch<SetStateAction<ManagedUserDraft>>;
  isSavingUser: boolean;
  onSaveUser: (event: FormEvent) => void;
  onCloseUserModal: () => void;
}

function UserAvatar({ name }: { name: string }) {
  const label = (name || '用户').trim().slice(0, 1).toUpperCase();
  return (
    <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-xs font-bold text-indigo-700 ring-1 ring-indigo-200 dark:bg-indigo-950/60 dark:text-indigo-300 dark:ring-indigo-800">
      {label}
    </span>
  );
}

export function SystemSettingsPage(props: SystemSettingsPageProps) {
  const closeUserModal = props.onCloseUserModal;
  return (
    <>
      <ManagementPage>
        <ManagementHeader
          icon={<Settings className="h-5 w-5 text-indigo-500" />}
          title="系统设置"
          description="管理系统连接参数、当前会话与本地账户权限。"
        />

        <div className="management-card space-y-6">
          <section className="space-y-2">
            <h3 className="flex items-center gap-1.5 text-xs font-bold uppercase text-slate-800 dark:text-slate-200">
              <Users className="h-4 w-4 text-indigo-500" /> 当前会话上下文 ( User Context )
            </h3>
            <div className="grid grid-cols-1 gap-4 text-xs font-mono sm:grid-cols-2">
              <div className="rounded-lg border border-slate-100 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-800/40"><strong>用户账户 ID：</strong> {props.userContext.user_id}</div>
              <div className="rounded-lg border border-slate-100 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-800/40"><strong>用户显示姓名：</strong> {props.userContext.display_name}</div>
            </div>
          </section>

          <section className="space-y-3.5 border-t border-slate-100 pt-5 dark:border-slate-800">
            <h3 className="flex items-center gap-1.5 text-xs font-bold uppercase text-slate-800 dark:text-slate-200">
              <KeyRound className="h-4 w-4 text-indigo-500" /> 大语言模型 LLM 连接配置
            </h3>
            <form onSubmit={props.onSaveLlm} className="grid grid-cols-1 gap-4 text-xs sm:grid-cols-2">
              <SettingsInput label="接口 Base URL" value={props.llmBaseUrl} onChange={props.setLlmBaseUrl} placeholder="https://api.openai.com/v1" />
              <SettingsInput label="调用模型 Model" value={props.llmModel} onChange={props.setLlmModel} placeholder="gpt-4" />
              <SettingsInput label="模型 API Key（可修改）" type="password" value={props.llmApiKey} onChange={props.setLlmApiKey} placeholder={props.llmSettings?.api_key_mask ? `当前 ${props.llmSettings.api_key_mask}；输入新 Key 后保存` : '输入 API Key 后保存'} />
              <SettingsInput label="接口超时时长 (秒)" type="number" value={props.llmTimeout} onChange={props.setLlmTimeout} placeholder="60" />
              <div className="col-span-2 flex justify-end gap-2 pt-1">
                <ActionButton type="button" onClick={props.onProbeLlm} disabled={props.isProbingLlm}>
                  {props.isProbingLlm && <RefreshCw className="h-3 w-3 animate-spin" />} 测试模型连接
                </ActionButton>
                <ActionButton type="submit" variant="primary" disabled={props.isSavingLlm} className="text-[10px]">
                  {props.isSavingLlm && <RefreshCw className="h-3 w-3 animate-spin" />} 更新 LLM 连接参数
                </ActionButton>
              </div>
              {props.llmProbe && (
                <div className={`col-span-2 rounded-lg border px-3 py-2 text-xs ${props.llmProbe.healthy ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/20 dark:text-emerald-300' : 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950/20 dark:text-rose-300'}`}>
                  {props.llmProbe.healthy ? `连接正常 · ${props.llmProbe.latency_ms}ms` : `连接失败 · ${props.llmProbe.message}`}
                </div>
              )}
            </form>
          </section>
        </div>

        <div className="management-card space-y-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h3 className="flex items-center gap-1.5 text-xs font-bold text-slate-800 dark:text-slate-200"><Users className="h-4 w-4 text-indigo-500" /> 用户与权限</h3>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">管理员可以管理数据库、领域包与系统设置；一般用户仅使用智能问数和个人空间。</p>
            </div>
            <ActionButton type="button" variant="primary" onClick={props.onCreateUser} className="shrink-0 px-3"><UserPlus className="h-3.5 w-3.5" /> 新建用户</ActionButton>
          </div>
          <div className="overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 text-[10px] text-slate-500 dark:bg-slate-950 dark:text-slate-400"><tr><th className="px-3 py-2 font-semibold">账户</th><th className="px-3 py-2 font-semibold">显示名称</th><th className="px-3 py-2 font-semibold">角色</th><th className="px-3 py-2 text-right font-semibold">操作</th></tr></thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {props.managedUsers.map(user => (
                  <tr key={user.user_id} className="text-slate-700 dark:text-slate-200">
                    <td className="px-3 py-2"><div className="flex min-w-0 items-center gap-2"><UserAvatar name={user.display_name || user.user_id} /><span className="truncate font-mono">{user.user_id}</span></div></td>
                    <td className="max-w-48 truncate px-3 py-2" title={user.display_name}>{user.display_name}</td>
                    <td className="px-3 py-2"><RolePicker value={user.role} onChange={role => props.onRoleChange(user.user_id, role)} /></td>
                    <td className="whitespace-nowrap px-3 py-2 text-right"><button type="button" onClick={() => props.onEditUser(user)} className="mr-3 text-[11px] font-bold text-indigo-600 hover:text-indigo-700 dark:text-indigo-400">编辑</button>{user.user_id !== props.userContext.user_id && <button type="button" onClick={() => props.onDeleteUser(user.user_id)} className="text-[11px] font-bold text-rose-600 hover:text-rose-700 dark:text-rose-400">删除</button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </ManagementPage>

      {props.userModalOpen && (
        <ModalFrame className="max-w-md" onBackdropClick={closeUserModal}>
          <form onSubmit={props.onSaveUser}>
            <div className="flex items-start justify-between border-b border-slate-100 pb-4 dark:border-slate-800">
              <div><h3 className="flex items-center gap-2 text-sm font-bold text-slate-900 dark:text-white"><UserPlus className="h-4 w-4 text-indigo-500" /> {props.editingUsername ? '编辑用户' : '新建用户'}</h3><p className="mt-1 text-xs text-slate-500 dark:text-slate-400">修改登录信息、显示名称与账户权限。</p></div>
              <button type="button" onClick={closeUserModal} aria-label="关闭用户窗口" className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"><X className="h-4 w-4" /></button>
            </div>
            <div className="mt-4 grid grid-cols-1 gap-4 text-xs sm:grid-cols-2">
              <SettingsInput required autoFocus label="登录用户名" value={props.userDraft.username} onChange={username => props.setUserDraft(value => ({ ...value, username }))} placeholder="例如 analyst_01" />
              <SettingsInput label="显示名称" value={props.userDraft.display_name} onChange={display_name => props.setUserDraft(value => ({ ...value, display_name }))} placeholder="例如 数据分析员" />
              <SettingsInput required={!props.editingUsername} minLength={props.userDraft.password ? 8 : undefined} label={props.editingUsername ? '新密码（可选）' : '初始密码'} type="password" value={props.userDraft.password} onChange={password => props.setUserDraft(value => ({ ...value, password }))} placeholder={props.editingUsername ? '不修改请留空' : '至少 8 位'} />
              <div><label className="mb-1 block font-semibold text-slate-600 dark:text-slate-300">角色</label><RolePicker value={props.userDraft.role} onChange={role => props.setUserDraft(value => ({ ...value, role }))} fullWidth /></div>
            </div>
            <div className="mt-5 flex justify-end gap-2"><ActionButton type="button" onClick={closeUserModal}>取消</ActionButton><ActionButton type="submit" variant="primary" disabled={props.isSavingUser}>{props.isSavingUser ? '保存中…' : props.editingUsername ? '保存修改' : '创建用户'}</ActionButton></div>
          </form>
        </ModalFrame>
      )}
    </>
  );
}

function SettingsInput({ label, onChange, ...props }: Omit<InputHTMLAttributes<HTMLInputElement>, 'onChange'> & { label: string; onChange: (value: string) => void }) {
  return <div><label className="mb-1 block text-[10px] font-semibold text-slate-400">{label}</label><input {...props} onChange={event => onChange(event.target.value)} className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-slate-800 outline-none focus:border-indigo-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200" /></div>;
}

function RolePicker({ value, onChange, fullWidth = false }: { value: 'admin' | 'user'; onChange: (role: 'admin' | 'user') => void; fullWidth?: boolean }) {
  return <div className={`${fullWidth ? 'grid grid-cols-2' : 'inline-flex'} rounded-lg bg-slate-100 p-0.5 dark:bg-slate-800`}><button type="button" onClick={() => onChange('user')} className={`rounded-md px-2.5 py-1 text-[10px] font-bold transition-colors ${value === 'user' ? 'bg-white text-indigo-700 shadow-sm dark:bg-slate-700 dark:text-indigo-300' : 'text-slate-500'}`}>一般用户</button><button type="button" onClick={() => onChange('admin')} className={`rounded-md px-2.5 py-1 text-[10px] font-bold transition-colors ${value === 'admin' ? 'bg-white text-indigo-700 shadow-sm dark:bg-slate-700 dark:text-indigo-300' : 'text-slate-500'}`}>管理员</button></div>;
}
