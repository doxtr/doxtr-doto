/*
 * doto-views.js — client-side interactions for doto-list layout views.
 *
 * Vendored, dependency-free (vanilla JS). Registered via app.add_js_file for
 * HTML builders only. Every initializer is DEFENSIVE: it no-ops when the
 * relevant containers are absent on a page, so including this script on pages
 * without a doto-list view (or with only table/cards/simple views) is safe.
 *
 * Nothing here persists to a backend — a static Sphinx build has none. Kanban
 * drag, calendar day reveal, and email pane selection are purely visual /
 * in-page. A page reload restores the server-rendered state.
 */
(function () {
  "use strict";

  /* ---- Kanban: drag cards between status columns (visual only) ---------- */
  function initKanban(root) {
    var dragged = null;

    root.querySelectorAll(".doto-kanban-card").forEach(function (card) {
      card.addEventListener("dragstart", function () {
        dragged = card;
        card.classList.add("doto-kanban-card-dragging");
      });
      card.addEventListener("dragend", function () {
        card.classList.remove("doto-kanban-card-dragging");
        dragged = null;
      });
    });

    root.querySelectorAll("[data-doto-dropzone]").forEach(function (zone) {
      zone.addEventListener("dragover", function (e) {
        e.preventDefault();
        zone.classList.add("doto-kanban-dropzone-active");
      });
      zone.addEventListener("dragleave", function () {
        zone.classList.remove("doto-kanban-dropzone-active");
      });
      zone.addEventListener("drop", function (e) {
        e.preventDefault();
        zone.classList.remove("doto-kanban-dropzone-active");
        if (!dragged) {
          return;
        }
        var status = zone.getAttribute("data-doto-dropzone") || "";
        zone.appendChild(dragged);
        dragged.setAttribute("data-doto-status", status);
        var badge = dragged.querySelector("[data-doto-status-badge]");
        if (badge) {
          badge.textContent = status;
        }
      });
    });
  }

  /* ---- Calendar: click a day to toggle its task panel ------------------- */
  function initCalendar(root) {
    root.querySelectorAll("[data-doto-day-toggle]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var iso = btn.getAttribute("data-doto-day-toggle");
        var cell = btn.closest(".doto-calendar-day");
        if (!cell) {
          return;
        }
        var open = cell.classList.toggle("doto-calendar-day-open");
        // Collapse other open days so only one panel shows at a time.
        if (open) {
          root
            .querySelectorAll(".doto-calendar-day-open")
            .forEach(function (other) {
              if (other !== cell) {
                other.classList.remove("doto-calendar-day-open");
              }
            });
        }
      });
    });
  }

  /* ---- Email: tree filter + list-row selection populates detail --------- */
  function initEmail(root) {
    var items = root.querySelectorAll("[data-doto-select]");
    var panels = root.querySelectorAll("[data-doto-detail]");

    function selectTask(id) {
      panels.forEach(function (panel) {
        var match = panel.getAttribute("data-doto-detail") === id;
        if (match) {
          panel.removeAttribute("hidden");
        } else {
          panel.setAttribute("hidden", "");
        }
      });
      items.forEach(function (item) {
        item.classList.toggle(
          "doto-email-list-item-selected",
          item.getAttribute("data-doto-select") === id
        );
      });
    }

    items.forEach(function (item) {
      function activate() {
        selectTask(item.getAttribute("data-doto-select"));
      }
      item.addEventListener("click", activate);
      item.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          activate();
        }
      });
    });

    root.querySelectorAll("[data-doto-tree-filter]").forEach(function (node) {
      node.addEventListener("click", function () {
        var status = node.getAttribute("data-doto-tree-filter") || "";
        items.forEach(function (item) {
          var show = !status || item.getAttribute("data-doto-status") === status;
          item.classList.toggle("doto-email-list-item-filtered", !show);
        });
        root
          .querySelectorAll(".doto-email-tree-node-active")
          .forEach(function (n) {
            n.classList.remove("doto-email-tree-node-active");
          });
        node.classList.add("doto-email-tree-node-active");
      });
    });
  }

  function init() {
    document
      .querySelectorAll('[data-doto-view="kanban"]')
      .forEach(initKanban);
    document
      .querySelectorAll('[data-doto-view="calendar"]')
      .forEach(initCalendar);
    document
      .querySelectorAll('[data-doto-view="email"]')
      .forEach(initEmail);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
