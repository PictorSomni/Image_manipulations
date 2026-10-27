// Notifications de Claude (voir push.py) ; un toucher ouvre la page.
self.addEventListener("push", e => {
  const d = e.data ? e.data.json() : {title: "Claude", body: ""};
  e.waitUntil(self.registration.showNotification(d.title,
    {body: d.body, icon: "/icon.png"}));
});
self.addEventListener("notificationclick", e => {
  e.notification.close();
  e.waitUntil(clients.matchAll({type: "window"}).then(list =>
    list.length ? list[0].focus() : clients.openWindow("/")));
});
