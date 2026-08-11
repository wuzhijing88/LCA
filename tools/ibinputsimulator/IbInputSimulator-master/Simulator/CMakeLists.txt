cmake_minimum_required(VERSION 3.15)

project(IbInputSimulator)

set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

# IbWinCppLib must already exist locally.
set(IB_WIN_CPP_LIB_DIR "" CACHE PATH "Path to a local IbWinCppLib source tree")
if(NOT IB_WIN_CPP_LIB_DIR OR NOT EXISTS "${IB_WIN_CPP_LIB_DIR}/CMakeLists.txt")
    message(FATAL_ERROR "Set IB_WIN_CPP_LIB_DIR to a local IbWinCppLib source tree")
endif()
add_subdirectory("${IB_WIN_CPP_LIB_DIR}" "${CMAKE_CURRENT_BINARY_DIR}/IbWinCppLib")

# Detours
find_path(DETOURS_INCLUDE_DIR detours/detours.h)
find_library(DETOURS_LIBRARY detours)

# RapidJSON
find_package(RapidJSON CONFIG REQUIRED)


set(sourceFiles
    dllmain.cpp
    "API 2.cpp"
    "API 3.cpp"
)
list(TRANSFORM sourceFiles PREPEND source/)
add_library(IbInputSimulator SHARED ${sourceFiles})
target_compile_features(IbInputSimulator PUBLIC cxx_std_20)
target_compile_definitions(IbInputSimulator PRIVATE IB_INPUT_DLLEXPORT)

set(PROJECT_VERSION_MAJOR 0)
set(PROJECT_VERSION_MINOR 4)
set(PROJECT_VERSION_PATCH 1)
configure_file(source/resource.rc.cmake.in resource.rc @ONLY)
target_sources(IbInputSimulator PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/resource.rc")

target_include_directories(IbInputSimulator
    PUBLIC include
    PRIVATE ${DETOURS_INCLUDE_DIR}
)
target_link_libraries(IbInputSimulator
    PRIVATE IbWinCpp    
    PRIVATE ${DETOURS_LIBRARY}
    PRIVATE rapidjson
)

# Test
if(CMAKE_PROJECT_NAME STREQUAL PROJECT_NAME)
    option(BUILD_TESTING "Build the testing tree." OFF)
    include(CTest)
    if(BUILD_TESTING)
        find_package(Boost REQUIRED COMPONENTS unit_test_framework)
        find_package(fmt CONFIG REQUIRED)

        set(testFiles
            test.cpp
        )
        list(TRANSFORM testFiles PREPEND test/)

        add_executable(IbInputSimulator_Test ${testFiles})
        target_link_libraries(IbInputSimulator_Test
            PRIVATE IbInputSimulator
            PRIVATE Boost::unit_test_framework
            PRIVATE IbWinCpp
            PRIVATE fmt::fmt
        )
    endif()
endif()
