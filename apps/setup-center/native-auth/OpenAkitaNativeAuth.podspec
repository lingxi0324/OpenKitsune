Pod::Spec.new do |s|
  s.name = 'OpenKitsuneNativeAuth'
  s.version = '1.0.0'
  s.summary = 'OpenKitsune system browser authorization bridge'
  s.license = 'AGPL-3.0-only'
  s.homepage = 'https://github.com/openkitsune/openkitsune'
  s.author = 'OpenKitsune'
  s.source = { :git => 'https://github.com/openkitsune/openkitsune.git' }
  s.source_files = 'ios/Sources/**/*.{swift,h,m}'
  s.ios.deployment_target = '15.0'
  s.dependency 'Capacitor'
  s.swift_version = '5.9'
end
