import { CheckCircle2 } from "lucide-react";
import { useState } from "react";

import { createAdminAccessRole, replaceAdminAccessRolePermissions, replaceAdminUserRoles, setAdminAccessRoleActive } from "../data";
import type { MessageKey } from "../i18n";
import type { AdminAccessPermission, AdminAccessRole, AdminIdentityUser, BrowserAdminSession } from "../types";

type AccessAction = "assign" | "create" | "permissions" | "reactivate" | "retire";

export function AdminAccessMutations({ session, currentUsername, permissions, roles, users, translate, refresh, onError }: {
  session: BrowserAdminSession;
  currentUsername: string;
  permissions: AdminAccessPermission[];
  roles: AdminAccessRole[];
  users: AdminIdentityUser[];
  translate: (key: MessageKey) => string;
  refresh: () => Promise<void>;
  onError: (error: unknown) => void;
}) {
  const [action, setAction] = useState<AccessAction | null>(null);
  const [targetRole, setTargetRole] = useState<AdminAccessRole | null>(null);
  const [targetUser, setTargetUser] = useState<AdminIdentityUser | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [roleName, setRoleName] = useState("");
  const [roleDescription, setRoleDescription] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<MessageKey | null>(null);
  const [revokedSessions, setRevokedSessions] = useState<number | null>(null);

  const begin = (next: AccessAction, role?: AdminAccessRole, user?: AdminIdentityUser) => {
    setAction(next); setTargetRole(role ?? null); setTargetUser(user ?? null); setConfirmation(""); setNotice(null); setRevokedSessions(null);
    setSelected(next === "permissions" && role ? [...role.permissions] : next === "assign" && user ? roles.filter((item) => user.roles.includes(item.name)).map((item) => item.id) : []);
    if (next === "create") { setRoleName(""); setRoleDescription(""); }
  };
  const toggle = (value: string) => setSelected((current) => current.includes(value) ? current.filter((item) => item !== value) : [...current, value].sort());
  const expected = action === "create" ? "CREATE" : action === "permissions" ? "APPLY" : action === "retire" ? "RETIRE" : action === "reactivate" ? "REACTIVATE" : "ASSIGN";

  const submit = async (event: React.FormEvent) => {
    event.preventDefault(); if (!action || confirmation.trim() !== expected) return;
    setBusy(true); setNotice(null); setRevokedSessions(null);
    try {
      if (action === "create") {
        const result = await createAdminAccessRole(session, { name: roleName, description: roleDescription, permissions: selected });
        setNotice(result.transitioned ? "adminAccessRoleCreated" : "adminAccessNoChange"); setRevokedSessions(result.revokedSessions);
      } else if (action === "permissions" && targetRole) {
        const result = await replaceAdminAccessRolePermissions(session, targetRole, selected);
        setNotice(result.transitioned ? "adminAccessPermissionsReplaced" : "adminAccessNoChange"); setRevokedSessions(result.revokedSessions);
      } else if ((action === "retire" || action === "reactivate") && targetRole) {
        const result = await setAdminAccessRoleActive(session, targetRole, action === "reactivate");
        setNotice(result.transitioned ? (result.role.active ? "adminAccessRoleReactivated" : "adminAccessRoleRetired") : "adminAccessNoChange"); setRevokedSessions(result.revokedSessions);
      } else if (action === "assign" && targetUser) {
        const result = await replaceAdminUserRoles(session, targetUser, selected);
        setNotice(result.transitioned ? "adminAccessUserRolesReplaced" : "adminAccessNoChange"); setRevokedSessions(result.revokedSessions);
      } else return;
      await refresh(); setAction(null); setTargetRole(null); setTargetUser(null); setConfirmation("");
    } catch (error) { onError(error); }
    finally { setBusy(false); }
  };

  const permissionChoices = <fieldset className="admin-choice-grid"><legend>{translate("adminAccessPermissions")}</legend>{permissions.map((permission) => <label key={permission.name}><input type="checkbox" checked={selected.includes(permission.name)} onChange={() => toggle(permission.name)} /><span><strong>{permission.name}</strong><small>{permission.description}</small></span></label>)}</fieldset>;
  const activeRoles = roles.filter((role) => role.active);
  const roleChoices = <fieldset className="admin-choice-grid"><legend>{translate("adminAccessRoles")}</legend>{activeRoles.map((role) => <label key={role.id}><input type="checkbox" checked={selected.includes(role.id)} onChange={() => toggle(role.id)} /><span><strong>{role.name}</strong><small>{role.description}</small></span></label>)}</fieldset>;

  return <>
    {notice ? <p className="admin-security-status" role="status"><CheckCircle2 size={16} aria-hidden="true" />{translate(notice)}{revokedSessions !== null ? <span>{translate("adminIdentityRevokedSessions")}: {revokedSessions}</span> : null}</p> : null}
    <button className="primary-button" disabled={busy} onClick={() => begin("create")}>{translate("adminAccessCreateRole")}</button>
    <div className="table-scroll"><table className="live-table"><caption>{translate("adminAccessRoles")}</caption><thead><tr><th>{translate("adminAccessRole")}</th><th>{translate("adminAccessPermissions")}</th><th>{translate("adminAccessUsers")}</th><th>{translate("adminIdentityStatus")}</th><th>{translate("adminIdentityAction")}</th></tr></thead><tbody>{roles.map((role) => <tr key={role.id}><th scope="row"><strong>{role.name}</strong><small>{role.description}</small></th><td>{role.permissions.join(", ") || translate("adminAccessNoPermissions")}</td><td>{role.activeUserCount}</td><td>{role.active ? translate("adminIdentityActive") : translate("adminAccessRetired")}</td><td><div className="admin-table-actions"><button className="secondary-button" disabled={busy || !role.active} onClick={() => begin("permissions", role)}>{translate("adminAccessEditPermissions")}</button><button className={role.active ? "danger-button" : "secondary-button"} disabled={busy} onClick={() => begin(role.active ? "retire" : "reactivate", role)}>{role.active ? translate("adminAccessRetireRole") : translate("adminAccessReactivateRole")}</button></div></td></tr>)}</tbody></table></div>
    <div className="table-scroll"><table className="live-table"><caption>{translate("adminAccessUserAssignments")}</caption><thead><tr><th>{translate("adminIdentityUser")}</th><th>{translate("adminIdentityRoles")}</th><th>{translate("adminIdentityAction")}</th></tr></thead><tbody>{users.map((user) => <tr key={user.id}><th scope="row"><strong>{user.username}</strong><small>{user.displayName}</small></th><td>{user.roles.join(", ") || translate("adminIdentityNoRoles")}</td><td>{user.username.trim().toLocaleLowerCase() === currentUsername.trim().toLocaleLowerCase() ? <span>{translate("adminIdentityCurrentOperator")}</span> : <button className="secondary-button" disabled={busy || user.disabled} onClick={() => begin("assign", undefined, user)}>{translate("adminAccessManageUserRoles")}</button>}</td></tr>)}</tbody></table></div>
    <div className="table-scroll"><table className="live-table"><caption>{translate("adminAccessPermissions")}</caption><thead><tr><th>{translate("adminAccessPermission")}</th><th>{translate("adminAccessDescription")}</th><th>{translate("adminAccessRoleCount")}</th></tr></thead><tbody>{permissions.map((permission) => <tr key={permission.name}><th scope="row">{permission.name}</th><td>{permission.description}</td><td>{permission.activeRoleCount}</td></tr>)}</tbody></table></div>
    {action ? <form className="admin-form admin-access-action" aria-label={translate("adminAccessChangeTitle")} onSubmit={submit}><h3>{translate(action === "create" ? "adminAccessCreateRoleTitle" : action === "permissions" ? "adminAccessPermissionsTitle" : action === "assign" ? "adminAccessAssignmentTitle" : action === "retire" ? "adminAccessRetireTitle" : "adminAccessReactivateTitle")}</h3>{action === "create" ? <><label>{translate("adminAccessRoleName")}<input required pattern="[a-z][a-z0-9_.-]{0,63}" value={roleName} onChange={(event) => setRoleName(event.target.value)} /></label><label>{translate("adminAccessDescription")}<textarea maxLength={500} value={roleDescription} onChange={(event) => setRoleDescription(event.target.value)} /></label>{permissionChoices}</> : null}{action === "permissions" ? <><p><strong>{targetRole?.name}</strong></p>{permissionChoices}</> : null}{action === "assign" ? <><p><strong>{targetUser?.username}</strong></p>{roleChoices}</> : null}{action === "retire" || action === "reactivate" ? <><p>{translate(action === "retire" ? "adminAccessRetireWarning" : "adminAccessReactivateWarning")}</p><p><strong>{targetRole?.name}</strong></p></> : null}<label>{translate("adminAccessTypeConfirmation")} <strong>{expected}</strong><input required value={confirmation} onChange={(event) => setConfirmation(event.target.value)} autoComplete="off" placeholder={expected} /></label><p>{translate("adminAccessMutationWarning")}</p><div className="admin-action-row"><button className={action === "retire" ? "danger-button" : "primary-button"} disabled={busy || confirmation.trim() !== expected}>{translate("adminAccessConfirmChange")}</button><button type="button" className="secondary-button" disabled={busy} onClick={() => setAction(null)}>{translate("adminIdentityCancel")}</button></div></form> : null}
  </>;
}
