// SPDX-License-Identifier: GPL-3.0-or-later
#include "server.hpp"
#include "selftest.hpp"
#include <QCommandLineParser>
#include <QCoreApplication>
#include <QDir>
#include <QTextStream>
#include <sys/stat.h>
#include <unistd.h>

int main(int argc, char **argv)
{
    ::umask(0077);
    QCoreApplication application(argc, argv);
    QCoreApplication::setApplicationName("rgbcd");
    QCoreApplication::setApplicationVersion("0.1.0");
    QCommandLineParser parser;
    parser.addHelpOption();
    parser.addVersionOption();
    parser.addOption({"demo", "Serve simulated sensors and lighting only"});
    parser.addOption({"listen", "Bind a private socket for tests/demo", "path"});
    parser.addOption({"hwmon-root", "Override the read-only hwmon root for tests", "path",
                      "/sys/class/hwmon"});
    parser.addOption({"self-test", "Run native checks without real hardware"});
    parser.process(application);
    if (parser.isSet("self-test")) {
        return runSelfTests();
    }
    QString error;
    Server server(parser.isSet("demo"), parser.value("hwmon-root"));
    bool listening = false;
    if (parser.isSet("listen")) {
        listening = server.listen(parser.value("listen"), error);
    } else {
        const QByteArray pid = qgetenv("LISTEN_PID");
        const QByteArray descriptors = qgetenv("LISTEN_FDS");
        const bool activationPresent = !pid.isEmpty() || !descriptors.isEmpty();
        const bool activationValid = pid == QByteArray::number(::getpid()) && descriptors == "1";
        qunsetenv("LISTEN_PID");
        qunsetenv("LISTEN_FDS");
        qunsetenv("LISTEN_FDNAMES");
        if (activationValid) {
            listening = server.adopt(3, error);
        } else if (!activationPresent && parser.isSet("demo")) {
            const QString runtime = qEnvironmentVariable("XDG_RUNTIME_DIR");
            if (runtime.isEmpty() || !QDir::isAbsolutePath(runtime)) {
                error = "Demo requires --listen or an absolute XDG_RUNTIME_DIR";
            } else {
                listening = server.listen(runtime + "/omarchy-rgb-cooling.sock", error);
            }
        } else {
            error = "Expected LISTEN_PID for this process and exactly one LISTEN_FDS descriptor";
        }
    }
    if (!listening) {
        QTextStream(stderr) << error << '\n';
        return 1;
    }
    return application.exec();
}
