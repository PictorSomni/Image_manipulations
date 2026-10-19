#!/bin/zsh
# Build de l'app Hub (coquille) pour macOS → ~/Applications/Hub.app
# Contourne 2 bugs du modèle Flet 1.0 avec Xcode 27 : cible macOS 11 refusée,
# jni épinglé trop vieux. ponytail: à retirer quand Flet les corrige.
set -e
cd "$(dirname "$0")"
export PATH=/opt/homebrew/bin:$PATH
V=~/.hub_build_venv
[ -x $V/bin/flet ] || { /opt/homebrew/bin/python3.14 -m venv $V && $V/bin/pip -q install "flet[all]==1.0.4"; }
$V/bin/flet build macos --arch arm64 --no-compile-packages --yes -v || true          # génère build/flutter (échoue à xcodebuild)
F=build/flutter
export PATH=$(ls -d ~/flutter/*/bin | tail -1):$PATH
sed -i "" -E "s/MACOSX_DEPLOYMENT_TARGET = 1[01][.0-9]*;/MACOSX_DEPLOYMENT_TARGET = 12.0;/g" $F/macos/Runner.xcodeproj/project.pbxproj
sed -i "" -E "s/^#? *platform :osx, .*/platform :osx, \"12.0\"/" $F/macos/Podfile
grep -q 'MACOSX_DEPLOYMENT_TARGET"] = "12.0"' $F/macos/Podfile || sed -i "" 's/    flutter_additional_macos_build_settings(target)/&\
    target.build_configurations.each { |c| c.build_settings["MACOSX_DEPLOYMENT_TARGET"] = "12.0" }/' $F/macos/Podfile
sed -i "" "s/^  jni: 1.0.0/  jni: ^1.1.0/" $F/pubspec.yaml
# pyobjc embarque ses tests avec des .dSYM que `strip` d'Xcode 27 refuse.
find build ~/.pub-cache/hosted/pub.dev/serious_python_darwin-* \( -name PyObjCTest -o -name "*.dSYM" \) -prune -exec rm -rf {} + 2>/dev/null || true
(cd $F && flutter pub get && flutter build macos --release)
mkdir -p ~/Applications && rm -rf ~/Applications/Hub.app
cp -R $F/build/macos/Build/Products/Release/*.app ~/Applications/Hub.app
echo "OK → ~/Applications/Hub.app"
