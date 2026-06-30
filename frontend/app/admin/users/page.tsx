'use client';

/**
 * 后台用户管理
 *
 * 两种角色：
 * - admin：完整后台 + Mission 会话权限
 * - user：**仅**Mission 会话权限；登录后只能看到 Mission 列表（点眼睛进入会话）
 */
import { useEffect, useState } from 'react';
import { AxiosError } from 'axios';
import { useTranslation } from 'react-i18next';
import { Pencil, Trash2, UserPlus } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select } from '@/components/ui/select';
import {
  usersApi,
  type UserCreateInput,
  type UserRole,
  type UserUpdateInput,
} from '@/lib/api/users';
import { useAuthStore } from '@/stores/authStore';
import { useConfirm, useToast } from '@/components/providers/ConfirmProvider';
import type { UserPublic } from '@/types/api';

/** 超级管理员 username，与后端 `user_service.SUPER_ADMIN_USERNAME` 保持一致。 */
const SUPER_ADMIN_USERNAME = 'admin';

export default function AdminUsersPage() {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const toast = useToast();
  const [users, setUsers] = useState<UserPublic[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<UserPublic | null>(null);

  const me = useAuthStore((s) => s.user);
  const isSuperAdmin = me?.username === SUPER_ADMIN_USERNAME;

  async function refresh() {
    setLoading(true);
    try {
      const rows = await usersApi.list();
      setUsers(rows);
    } catch (e) {
      setErr(e instanceof Error ? e.message : t('users.loadFailed'));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function handleDelete(u: UserPublic) {
    if (
      !(await confirm({
        message: t('users.deleteConfirm', { name: u.username }),
        danger: true,
        confirmText: t('common.delete'),
      }))
    )
      return;
    try {
      await usersApi.remove(u.id);
      await refresh();
    } catch (e) {
      toast(
        e instanceof AxiosError
          ? (e.response?.data?.detail ?? e.message)
          : t('users.deleteFailed'),
        'error',
      );
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-8 py-8">
      <header className="mb-5 flex items-center justify-between border-b border-border pb-4">
        <div>
          <h1 className="text-xl font-semibold text-foreground">{t('users.title')}</h1>
          <p className="text-xs text-muted-foreground/70">
            {t('users.subtitle')}
            {!isSuperAdmin && (
              <span className="ml-1 text-warning">
                {t('users.superAdminOnlyHintPrefix')}
                <code className="font-mono">admin</code>
                {t('users.superAdminOnlyHintSuffix')}
              </span>
            )}
          </p>
        </div>
        <Button size="sm" onClick={() => setCreateOpen(true)}>
          <UserPlus className="mr-1.5 h-3.5 w-3.5" />
          {t('users.newUser')}
        </Button>
      </header>

      {err && (
        <p className="mb-4 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {err}
        </p>
      )}

      <div className="overflow-hidden rounded-lg border border-border bg-card">
        {loading ? (
          <p className="p-8 text-center text-sm text-muted-foreground/70">
            {t('common.loading')}
          </p>
        ) : users.length === 0 ? (
          <p className="p-8 text-center text-sm text-muted-foreground/70">
            {t('users.emptyUsers')}
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground/70">
                <th className="px-4 py-2.5 font-medium">{t('users.colUsername')}</th>
                <th className="px-4 py-2.5 font-medium">{t('users.colEmail')}</th>
                <th className="px-4 py-2.5 font-medium">{t('users.colRole')}</th>
                <th className="px-4 py-2.5 font-medium">{t('users.colStatus')}</th>
                <th className="px-4 py-2.5 font-medium">{t('users.colCreatedAt')}</th>
                <th className="px-4 py-2.5 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr
                  key={u.id}
                  className="border-b border-border last:border-b-0 hover:bg-accent/50"
                >
                  <td className="px-4 py-3 font-medium text-foreground">
                    {u.username}
                    {me?.id === u.id && (
                      <span className="ml-1.5 text-[10px] text-success">
                        {t('users.youTag')}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">{u.email}</td>
                  <td className="px-4 py-3">
                    <Badge variant={u.role === 'admin' ? 'default' : 'secondary'}>
                      {u.role === 'admin' ? t('users.roleAdmin') : t('users.roleUser')}
                    </Badge>
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={u.is_active ? 'success' : 'secondary'}>
                      {u.is_active ? t('users.statusActive') : t('users.statusInactive')}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 text-xs text-muted-foreground/70">
                    {new Date(u.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button size="sm" variant="ghost" onClick={() => setEditing(u)}>
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={me?.id === u.id}
                        title={me?.id === u.id ? t('users.cannotDeleteSelf') : t('common.delete')}
                        onClick={() => handleDelete(u)}
                      >
                        <Trash2 className="h-3.5 w-3.5 text-destructive" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <CreateUserDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onSaved={refresh}
        isSuperAdmin={isSuperAdmin}
      />
      <EditUserDialog
        user={editing}
        onClose={() => setEditing(null)}
        onSaved={refresh}
        meId={me?.id}
        isSuperAdmin={isSuperAdmin}
      />
    </div>
  );
}

function CreateUserDialog({
  open,
  onClose,
  onSaved,
  isSuperAdmin,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => Promise<void> | void;
  /** 当前登录者是否为超级管理员（username='admin'）。非超级管理员不能创建 admin 账号。 */
  isSuperAdmin: boolean;
}) {
  const { t } = useTranslation();
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<UserRole>('user');
  const [isActive, setIsActive] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      setUsername('');
      setEmail('');
      setPassword('');
      setRole('user');
      setIsActive(true);
      setErr(null);
      setSubmitting(false);
    }
  }, [open]);

  async function submit() {
    if (submitting) return;
    setErr(null);
    setSubmitting(true);
    try {
      const body: UserCreateInput = {
        username,
        email,
        password,
        role,
        is_active: isActive,
      };
      await usersApi.create(body);
      await onSaved();
      onClose();
    } catch (e) {
      setErr(
        e instanceof AxiosError
          ? (e.response?.data?.detail ?? e.message)
          : t('users.createFailed'),
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={t('users.newUser')}>
      <div className="space-y-3">
        <div className="space-y-2">
          <Label>{t('users.colUsername')}</Label>
          <Input value={username} onChange={(e) => setUsername(e.target.value)} required />
        </div>
        <div className="space-y-2">
          <Label>{t('users.colEmail')}</Label>
          <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </div>
        <div className="space-y-2">
          <Label>{t('users.initialPasswordLabel')}</Label>
          <Input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={6}
            required
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label>{t('users.colRole')}</Label>
            <Select
              value={role}
              onChange={(e) => setRole(e.target.value as UserRole)}
              title={isSuperAdmin ? undefined : t('users.createAdminSuperOnly')}
            >
              <option value="user">{t('users.roleUserOption')}</option>
              <option value="admin" disabled={!isSuperAdmin}>
                {isSuperAdmin
                  ? t('users.roleAdminOption')
                  : t('users.roleAdminOptionSuperOnly')}
              </option>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>{t('users.colStatus')}</Label>
            <Select
              value={isActive ? 'on' : 'off'}
              onChange={(e) => setIsActive(e.target.value === 'on')}
            >
              <option value="on">{t('users.statusActive')}</option>
              <option value="off">{t('users.statusInactive')}</option>
            </Select>
          </div>
        </div>
        {err && (
          <p className="rounded bg-destructive/10 px-3 py-2 text-xs text-destructive">{err}</p>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" size="sm" onClick={onClose} disabled={submitting}>
            {t('common.cancel')}
          </Button>
          <Button
            size="sm"
            onClick={submit}
            disabled={submitting || !username || !email || password.length < 6}
          >
            {submitting ? t('users.creating') : t('common.create')}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

function EditUserDialog({
  user,
  onClose,
  onSaved,
  meId,
  isSuperAdmin,
}: {
  user: UserPublic | null;
  onClose: () => void;
  onSaved: () => Promise<void> | void;
  meId?: string;
  /** 当前登录者是否为超级管理员；非超级管理员不能把非 admin 用户提升为 admin。 */
  isSuperAdmin: boolean;
}) {
  const { t } = useTranslation();
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<UserRole>('user');
  const [isActive, setIsActive] = useState(true);
  const [password, setPassword] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (user) {
      setEmail(user.email);
      setRole(user.role);
      setIsActive(user.is_active);
      setPassword('');
      setErr(null);
    }
  }, [user]);

  if (!user) return null;
  const isSelf = meId === user.id;
  // 非超级管理员 + 编辑的目标原本不是 admin → 禁止提升为 admin（与后端 user_service.update_user 一致）
  const adminOptionDisabled = !isSuperAdmin && user.role !== 'admin';

  async function submit() {
    if (submitting || !user) return;
    setErr(null);
    setSubmitting(true);
    try {
      const body: UserUpdateInput = {
        email: email || undefined,
        role,
        is_active: isActive,
        password: password.trim() ? password : undefined,
      };
      await usersApi.update(user.id, body);
      await onSaved();
      onClose();
    } catch (e) {
      setErr(
        e instanceof AxiosError
          ? (e.response?.data?.detail ?? e.message)
          : t('users.saveFailed'),
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog
      open={!!user}
      onClose={onClose}
      title={t('users.editUserTitle', { name: user.username })}
    >
      <div className="space-y-3">
        <div className="space-y-2">
          <Label>{t('users.colEmail')}</Label>
          <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label>{t('users.colRole')}</Label>
            <Select
              value={role}
              onChange={(e) => setRole(e.target.value as UserRole)}
              disabled={isSelf}
              title={
                isSelf
                  ? t('users.cannotChangeOwnRole')
                  : adminOptionDisabled
                    ? t('users.promoteAdminSuperOnly')
                    : undefined
              }
            >
              <option value="user">{t('users.roleUser')}</option>
              <option value="admin" disabled={adminOptionDisabled}>
                {adminOptionDisabled
                  ? t('users.roleAdminPromoteSuperOnly')
                  : t('users.roleAdmin')}
              </option>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>{t('users.colStatus')}</Label>
            <Select
              value={isActive ? 'on' : 'off'}
              onChange={(e) => setIsActive(e.target.value === 'on')}
              disabled={isSelf}
              title={isSelf ? t('users.cannotDeactivateSelf') : undefined}
            >
              <option value="on">{t('users.statusActive')}</option>
              <option value="off">{t('users.statusInactive')}</option>
            </Select>
          </div>
        </div>
        <div className="space-y-2">
          <Label>{t('users.resetPasswordLabel')}</Label>
          <Input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={t('users.resetPasswordPlaceholder')}
          />
        </div>
        {err && (
          <p className="rounded bg-destructive/10 px-3 py-2 text-xs text-destructive">{err}</p>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" size="sm" onClick={onClose} disabled={submitting}>
            {t('common.cancel')}
          </Button>
          <Button
            size="sm"
            onClick={submit}
            disabled={submitting || (!!password && password.length < 6)}
          >
            {submitting ? t('users.saving') : t('common.save')}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
