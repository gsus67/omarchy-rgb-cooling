// SPDX-License-Identifier: GPL-3.0-or-later
#include "server.hpp"
#include "openrgb.hpp"
#include <QPointer>
#include <utility>

void Server::dispatchLighting(Connection *connection, const Protocol::Request &request)
{
    Protocol::Reply reply;
    const auto &op = request.operation;
    if (op == "lighting.set" && !connection->allowLightingWrite()) {
        reply = Protocol::Reply::failure(
            "rate_limited", "At most 10 lighting.set requests per second");
    } else {
        auto ready = [this, peer = QPointer(connection), request] {
            if (!peer || !clients.contains(peer)) {
                return;
            }
            Protocol::Reply result;
            const auto &params = request.params;
            if (request.operation == "devices" || request.operation == "devices.rescan") {
                result.result = {{"devices", adapter->devices()}};
            } else if (request.operation == "lighting.get") {
                result = adapter->lighting(params.value("device").toString());
            } else if (request.operation == "lighting.save") {
                result = adapter->saveLighting(params.value("device").toString());
            } else {
                result = adapter->updateLighting(params);
            }
            peer->send(Protocol::response(request.id, result));
        };
        bool accepted = true;
        if (demo) {
            accepted = op != "devices.rescan" || !demoScan.isValid()
                || demoScan.elapsed() >= 2000;
            if (accepted) {
                if (!demoScan.isValid() || op == "devices.rescan") {
                    demoScan.start();
                }
                ready();
            }
        } else {
            auto *engine = static_cast<OpenRgbAdapter *>(adapter.get());
            engine->perform(op, request.params,
                [peer = QPointer(connection), id = request.id](const auto &result) {
                    if (peer) {
                        peer->send(Protocol::response(id, result));
                    }
                });
            return;
        }
        if (accepted) {
            return;
        }
        reply = Protocol::Reply::failure("rate_limited", "Scans must be at least 2 s apart");
    }
    connection->send(Protocol::response(request.id, reply));
}
